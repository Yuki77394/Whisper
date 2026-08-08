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


def main() -> None:
    try:
        config.validate()
    except RuntimeError as e:
        print(f"[fatal] {e}", file=sys.stderr)
        sys.exit(2)

    # Heroku: in-memory session (ephemeral FS would lose the session file).
    # Local / Docker: persist session file for faster restarts.
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

    # Register handlers
    start.register(app)
    inline.register(app, whisper_svc=whisper_service, log_svc=log_service)
    callbacks.register(app, whisper_svc=whisper_service, log_svc=log_service)
    commands.register(app, whisper_svc=whisper_service, log_svc=log_service)
    admin.register(app)

    # Lifecycle
    async def _on_startup():
        await init_db()
        await _post_startup(app)
        cleanup.start()
        log.info("WhisperX is up.")

    async def _on_shutdown():
        await cleanup.stop()
        log.info("WhisperX stopped.")

    app.loop.create_task(_on_startup())

    # Graceful shutdown
    def _sig(*_):
        log.info("Shutdown signal received…")
        asyncio.ensure_future(_on_shutdown())
        app.stop()

    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            app.loop.add_signal_handler(s, _sig)
        except NotImplementedError:
            # Windows fallback
            signal.signal(s, lambda *_: _sig())

    app.run()


if __name__ == "__main__":
    main()
