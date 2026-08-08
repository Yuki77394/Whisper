"""
WhisperX – central configuration loader.

All runtime values come from environment variables (see `.env.example`).
Nothing sensitive is ever hardcoded.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv

# Load .env if present (local dev). In Docker, env vars come from the runtime.
load_dotenv()


def _get_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"[config] WARN: {name}='{raw}' is not an int, using default {default}", file=sys.stderr)
        return default


def _get_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def _get_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on", "y"}


def _get_int_list(name: str) -> List[int]:
    raw = os.getenv(name, "")
    out: List[int] = []
    for chunk in raw.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            out.append(int(chunk))
        except ValueError:
            print(f"[config] WARN: ignoring non-int id '{chunk}' in {name}", file=sys.stderr)
    return out


@dataclass(frozen=True)
class Config:
    # Telegram
    api_id: int = field(default_factory=lambda: _get_int("API_ID", 0))
    api_hash: str = field(default_factory=lambda: _get_str("API_HASH", ""))
    bot_token: str = field(default_factory=lambda: _get_str("BOT_TOKEN", ""))

    # Mongo
    mongo_uri: str = field(default_factory=lambda: _get_str("MONGO_URI", "mongodb://localhost:27017"))
    mongo_db_name: str = field(default_factory=lambda: _get_str("MONGO_DB_NAME", "whisperx"))

    # Log group
    log_group_id: int = field(default_factory=lambda: _get_int("LOG_GROUP_ID", 0))

    # Admins
    owner_id: int = field(default_factory=lambda: _get_int("OWNER_ID", 0))
    admin_ids: tuple = field(default_factory=lambda: tuple(_get_int_list("ADMIN_IDS")))

    # Optional public chats
    support_chat: str = field(default_factory=lambda: _get_str("SUPPORT_CHAT", ""))
    update_channel: str = field(default_factory=lambda: _get_str("UPDATE_CHANNEL", ""))

    # Behaviour
    metadata_only_logs: bool = field(default_factory=lambda: _get_bool("METADATA_ONLY_LOGS", False))
    default_expiry_seconds: int = field(default_factory=lambda: _get_int("DEFAULT_EXPIRY_SECONDS", 0))
    inline_cache_seconds: int = field(default_factory=lambda: _get_int("INLINE_CACHE_SECONDS", 300))
    cleanup_interval_seconds: int = field(default_factory=lambda: _get_int("CLEANUP_INTERVAL_SECONDS", 300))
    rate_limit_per_minute: int = field(default_factory=lambda: _get_int("RATE_LIMIT_PER_MINUTE", 60))
    workers: int = field(default_factory=lambda: _get_int("WORKERS", 8))
    max_whisper_length: int = field(default_factory=lambda: _get_int("MAX_WHISPER_LENGTH", 4096))

    # Internal
    app_name: str = "WhisperX"
    app_version: str = "1.0.0"
    bot_username: str = ""    # populated at runtime
    bot_id: int = 0           # populated at runtime

    @property
    def all_admin_ids(self) -> List[int]:
        ids = set(self.admin_ids)
        if self.owner_id:
            ids.add(self.owner_id)
        return list(ids)

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.all_admin_ids

    def validate(self) -> None:
        missing = []
        if not self.api_id:
            missing.append("API_ID")
        if not self.api_hash:
            missing.append("API_HASH")
        if not self.bot_token:
            missing.append("BOT_TOKEN")
        if not self.mongo_uri:
            missing.append("MONGO_URI")
        if not self.owner_id:
            missing.append("OWNER_ID")
        if missing:
            raise RuntimeError(
                "Missing required environment variables: " + ", ".join(missing)
                + "\nSee .env.example for the full list."
            )


config = Config()
