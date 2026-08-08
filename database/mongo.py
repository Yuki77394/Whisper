"""
WhisperX – MongoDB connection + index bootstrap.

We use Motor (async PyMongo). Indexes are created on startup so the
runtime queries stay fast even at scale.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional, Any

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from config import config

log = logging.getLogger(__name__)


# ── Database handle proxy ───────────────────────────────────────────
# IMPORTANT: `db` is imported across the codebase via
#     `from database.mongo import db`
# Such imports capture the NAME at import time. If we ever did
#     global db; db = mongo_client[...]
# the rebinding would only update `database.mongo.db`; every other
# module's local `db` would still point to the previous value (None).
#
# Solution: `db` is a stable PROXY OBJECT whose identity never changes.
# Consumers capture the proxy at import time; at call time every
# attribute access is delegated to the *current* underlying database.
# `init_db()` swaps the underlying database by calling `db._set(...)`,
# which immediately makes every consumer see the new connection.
class _DbProxy:
    """Stable proxy that delegates attribute access to the live Motor db.

    Before init_db() is called, accessing any attribute raises a clear
    RuntimeError. After init_db(), all attribute access is forwarded to
    the real AsyncIOMotorDatabase.
    """

    __slots__ = ("_db",)

    def __init__(self) -> None:
        self._db: Optional[AsyncIOMotorDatabase] = None

    def _set(self, database: AsyncIOMotorDatabase) -> None:
        self._db = database

    def _clear(self) -> None:
        self._db = None

    @property
    def is_ready(self) -> bool:
        return self._db is not None

    def __getattr__(self, name: str) -> Any:
        # __getattr__ is only called when normal attribute lookup fails,
        # so self._db itself is retrieved via __slots__ / default.
        db = self._db
        if db is None:
            raise RuntimeError(
                "MongoDB is not initialized yet. Call init_db() before "
                "accessing any collection. (attempted attribute: "
                f"{name!r})"
            )
        return getattr(db, name)


# Public, stable handles — never rebind these names.
mongo_client: Optional[AsyncIOMotorClient] = None
db: _DbProxy = _DbProxy()


async def init_db() -> None:
    """Connect to MongoDB and ensure indexes exist."""
    global mongo_client

    client = AsyncIOMotorClient(
        config.mongo_uri,
        serverSelectionTimeoutMS=10000,
        maxPoolSize=100,
        minPoolSize=5,
        retryWrites=True,
    )

    # Quick connectivity check BEFORE publishing the client — if the
    # URI is wrong we want to fail fast and log a clear message.
    try:
        await client.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        log.critical("MongoDB connection failed: %s", e)
        print(f"[db] FATAL: cannot connect to MongoDB: {e}", file=sys.stderr)
        raise

    # Publish the live client + database. After this point, every
    # `db.<collection>` access in the codebase resolves to the real db.
    mongo_client = client
    db._set(client[config.mongo_db_name])

    await _ensure_indexes()
    log.info("MongoDB connected & indexed: %s", config.mongo_db_name)


async def ping_db() -> bool:
    if mongo_client is None:
        return False
    try:
        await mongo_client.admin.command("ping")
        return True
    except Exception:  # noqa: BLE001
        return False


# ── Indexes ──────────────────────────────────────────────────────────
#  Designed to match the actual query patterns used by the handlers.
async def _ensure_indexes() -> None:
    # users
    await db.users.create_index("user_id", unique=True)
    await db.users.create_index("username_lower")
    await db.users.create_index("created_at")

    # whispers
    await db.whispers.create_index("whisper_id", unique=True)
    await db.whispers.create_index("sender_id")
    await db.whispers.create_index("recipient_ids")
    await db.whispers.create_index("status")
    await db.whispers.create_index("expires_at")
    await db.whispers.create_index([("sender_id", 1), ("created_at", -1)])

    # whisper_access – who is allowed to open which whisper
    await db.whisper_access.create_index([("whisper_id", 1), ("user_id", 1)], unique=True)
    await db.whisper_access.create_index("whisper_id")
    await db.whisper_access.create_index("user_id")

    # history – per-user history projection
    await db.history.create_index([("user_id", 1), ("created_at", -1)])
    await db.history.create_index("whisper_id")

    # settings
    await db.settings.create_index("user_id", unique=True)

    # bans
    await db.bans.create_index("user_id", unique=True)

    # stats – daily counters
    await db.stats.create_index([("day", 1)], unique=True)

    # rate limit buckets (TTL collection)
    await db.rate_limits.create_index([("user_id", 1), ("bucket_minute", 1)], unique=True)
    await db.rate_limits.create_index("expires_at", expireAfterSeconds=0)

    # create_state for /create flow (auto-expire after 1 hour)
    await db.create_state.create_index("user_id", unique=True)
    await db.create_state.create_index("updated_at")

    log.info("All indexes ensured.")
