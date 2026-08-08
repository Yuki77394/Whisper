"""
WhisperX – MongoDB connection + index bootstrap.

We use Motor (async PyMongo). Indexes are created on startup so the
runtime queries stay fast even at scale.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from config import config

log = logging.getLogger(__name__)

mongo_client: Optional[AsyncIOMotorClient] = None
db: Optional[AsyncIOMotorDatabase] = None


async def init_db() -> None:
    """Connect to MongoDB and ensure indexes exist."""
    global mongo_client, db

    mongo_client = AsyncIOMotorClient(
        config.mongo_uri,
        serverSelectionTimeoutMS=10000,
        maxPoolSize=100,
        minPoolSize=5,
        retryWrites=True,
    )
    db = mongo_client[config.mongo_db_name]

    # Quick connectivity check
    try:
        await mongo_client.admin.command("ping")
    except Exception as e:  # noqa: BLE001
        log.critical("MongoDB connection failed: %s", e)
        print(f"[db] FATAL: cannot connect to MongoDB: {e}", file=sys.stderr)
        raise

    await _ensure_indexes()
    log.info("MongoDB connected & indexed: %s", config.mongo_db_name)


async def ping_db() -> bool:
    try:
        await mongo_client.admin.command("ping")  # type: ignore[union-attr]
        return True
    except Exception:  # noqa: BLE001
        return False


# ── Indexes ──────────────────────────────────────────────────────────
#  Designed to match the actual query patterns used by the handlers.
async def _ensure_indexes() -> None:
    # users
    await db.users.create_index("user_id", unique=True)  # type: ignore[union-attr]
    await db.users.create_index("username_lower")        # type: ignore[union-attr]
    await db.users.create_index("created_at")            # type: ignore[union-attr]

    # whispers
    await db.whispers.create_index("whisper_id", unique=True)  # type: ignore[union-attr]
    await db.whispers.create_index("sender_id")                # type: ignore[union-attr]
    await db.whispers.create_index("recipient_ids")            # type: ignore[union-attr]
    await db.whispers.create_index("status")                   # type: ignore[union-attr]
    await db.whispers.create_index("expires_at")               # type: ignore[union-attr]
    await db.whispers.create_index([("sender_id", 1), ("created_at", -1)])  # type: ignore[union-attr]

    # whisper_access – who is allowed to open which whisper
    await db.whisper_access.create_index([("whisper_id", 1), ("user_id", 1)], unique=True)  # type: ignore[union-attr]
    await db.whisper_access.create_index("whisper_id")  # type: ignore[union-attr]
    await db.whisper_access.create_index("user_id")     # type: ignore[union-attr]

    # history – per-user history projection
    await db.history.create_index([("user_id", 1), ("created_at", -1)])  # type: ignore[union-attr]
    await db.history.create_index("whisper_id")  # type: ignore[union-attr]

    # settings
    await db.settings.create_index("user_id", unique=True)  # type: ignore[union-attr]

    # bans
    await db.bans.create_index("user_id", unique=True)  # type: ignore[union-attr]

    # stats – daily counters
    await db.stats.create_index([("day", 1)], unique=True)  # type: ignore[union-attr]

    # rate limit buckets (TTL collection)
    await db.rate_limits.create_index([("user_id", 1), ("bucket_minute", 1)], unique=True)  # type: ignore[union-attr]
    await db.rate_limits.create_index("expires_at", expireAfterSeconds=0)  # type: ignore[union-attr]

    # create_state for /create flow (auto-expire after 1 hour)
    await db.create_state.create_index("user_id", unique=True)  # type: ignore[union-attr]
    await db.create_state.create_index("updated_at")  # type: ignore[union-attr]

    log.info("All indexes ensured.")
