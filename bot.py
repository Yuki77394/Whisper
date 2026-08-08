#!/usr/bin/env python3
"""
WhisperX – production-grade Telegram whisper bot.

Architecture
------------
* Pyrogram 2.x (async, MTProto)
* Motor (async MongoDB)
* Modular handlers / services / keyboards / utils
* Background cleanup worker
* Admin log group integration

Run
---
    cp .env.example .env
    # fill in API_ID / API_HASH / BOT_TOKEN / MONGO_URI / LOG_GROUP_ID / OWNER_ID
    pip install -r requirements.txt
    python bot.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from typing import Optional

from pyrogram import Client

from config import config
from database import init_db
from database.mongo import db
from database.users import UsersDB
from services.whisper import WhisperService
from services.logger import LogService
from services.cleanup import CleanupWorker
from handlers import start, inline, callbacks, commands, admin

# ── Logging ───────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
# Quiet noisy libs
logging.getLogger("pyrogram").setLevel(logging.WARNING)
logging.getLogger("motor").setLevel(logging.WARNING)
log = logging.getLogger("whisperx")

# ── Heroku detection ─────────────────────────────────────────────
# Heroku's filesystem is EPHEMERAL — any file written to disk is
# lost on every dyno restart. The Pyrogram session file would be
# wiped on every boot, causing an auth-key re-negotiation storm.
# So when running on Heroku (or any container with ephemeral FS),
# we keep the session in memory only. The bot re-authenticates
# with BOT_TOKEN on each boot (fast, <2s).
IS_HEROKU = bool(os.getenv("DYNO")) or bool(os.getenv("HEROKU_APP_NAME"))


async def _post_startup(client: Client) -> None:
    """Called once after login: ensure indexes, cache bot info, start workers."""
    me = await client.get_me()
    # Stash on config-like attribute so handlers can read it.
    # Config is a frozen dataclass — use object.__setattr__ to bypass.
    object.__setattr__(config, "bot_username", (me.username or "").lstrip("@"))
    object.__setattr__(config, "bot_id", me.id)
    log.info("Logged in as @%s (id=%s)", config.bot_username, config.bot_id)  # type: ignore[attr-defined]


async def _run_app() -> None:
    """Drive the full lifecycle explicitly.

    CRITICAL: We `await app.start()` so that Pyrogram finishes the full
    DH key exchange + bot_token sign-in BEFORE we call any authenticated
    API method. The previous implementation used `app.loop.create_task()`
    to run startup logic concurrently with `app.run()` → `app.start()`,
    which created a race where `client.get_me()` fired before the auth
    key was registered with Telegram, producing:

        AuthKeyUnregistered: [401 AUTH_KEY_UNREGISTERED] - The key is
        not registered in the system (caused by "users.GetFullUser")
    """
    use_in_memory = IS_HEROKU
    if use_in_memory:
        log.info("Heroku detected — using in-memory session (no file persisted).")

    app = Client(
        name="whisperx",
        api_id=config.api_id,
        api_hash=config.api_hash,
        bot_token=config.bot_token,
        workers=config.workers,
        in_memory=use_in_memory,
    )

    # Wire services
    log_service = LogService(app)
    whisper_service = WhisperService(log_service=log_service)
    cleanup = CleanupWorker(log_service=log_service)

    # Register handlers (must happen before start() so decorators bind)
    start.register(app)
    inline.register(app, whisper_svc=whisper_service, log_svc=log_service)
    callbacks.register(app, whisper_svc=whisper_service, log_svc=log_service)
    commands.register(app, whisper_svc=whisper_service, log_svc=log_service)
    admin.register(app)

    # ── Start the client FIRST ───────────────────────────────────────
    # This completes the full MTProto handshake + bot_token authorization.
    # Only after this returns is the auth key registered and any
    # authenticated RPC (get_me, send_message, etc.) safe to call.
    log.info("Starting Pyrogram client (authenticating with Telegram)…")
    await app.start()

    # ── Now safe to call authenticated APIs ──────────────────────────
    try:
        await init_db()
        await _post_startup(app)   # calls get_me() — safe now
        cleanup.start()
        log.info("WhisperX is up.")
    except Exception:
        # If startup logic fails, tear the client down cleanly.
        log.exception("Startup failed — stopping client.")
        await app.stop()
        raise

    # ── Wait for shutdown signal ─────────────────────────────────────
    stop_event = asyncio.Event()

    def _request_stop(*_):
        log.info("Shutdown signal received…")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, _request_stop)
        except NotImplementedError:
            # Windows fallback
            signal.signal(s, _request_stop)

    await stop_event.wait()

    # ── Graceful shutdown ────────────────────────────────────────────
    try:
        await cleanup.stop()
    except Exception:  # noqa: BLE001
        log.exception("Cleanup worker stop failed.")
    await app.stop()
    log.info("WhisperX stopped.")


def main() -> None:
    try:
        config.validate()
    except RuntimeError as e:
        print(f"[fatal] {e}", file=sys.stderr)
        sys.exit(2)

    try:
        asyncio.run(_run_app())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
