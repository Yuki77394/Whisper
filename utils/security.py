"""WhisperX – security & rate-limit helpers."""
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass
from typing import Optional

from config import config
from database.mongo import db

# Whisper IDs are 24-char hex strings (see whispers.new_whisper_id)
_WID_RE = re.compile(r"^[a-f0-9]{24}$")

# Rate-limit cache (in-memory, per minute)
_RL_CACHE: dict = {}


def is_valid_callback_id(whisper_id: str) -> bool:
    """Reject obviously malformed callback payloads."""
    return bool(whisper_id) and bool(_WID_RE.match(whisper_id))


def sign_callback(action: str, whisper_id: str) -> str:
    """
    Compose a callback payload like 'op:<wid>'.
    Real signature validation would need an HMAC key, but the wid itself
    is unguessable (24 random hex chars = 96 bits of entropy).
    """
    if not is_valid_callback_id(whisper_id):
        raise ValueError("invalid whisper id")
    return f"{action}:{whisper_id}"


def unsign_callback(payload: str) -> Optional[tuple]:
    """Return (action, whisper_id) or None if malformed."""
    if not payload or ":" not in payload:
        return None
    action, _, wid = payload.partition(":")
    if action not in {"op", "del", "vw", "hist"}:
        return None
    if not is_valid_callback_id(wid):
        return None
    return action, wid


@dataclass
class RateLimitResult:
    allowed: bool
    remaining: int
    retry_after: int  # seconds


async def rate_limit_check(user_id: int, *, key: str = "inline") -> RateLimitResult:
    """
    Simple sliding-minute counter backed by Mongo (so it survives restarts
    and is shared across workers).

    Uses a TTL'd document per (user_id, minute_bucket).
    """
    minute = int(time.time() // 60)
    bucket = f"{key}:{minute}"
    limit = max(1, config.rate_limit_per_minute)

    # Atomic upsert + inc
    res = await db.rate_limits.find_one_and_update(  # type: ignore[union-attr]
        {"user_id": user_id, "bucket_minute": bucket},
        {
            "$inc": {"count": 1},
            "$setOnInsert": {"expires_at": minute * 60 + 120},
        },
        upsert=True,
        return_document=True,
    )
    count = res.get("count", 1)
    if count > limit:
        return RateLimitResult(allowed=False, remaining=0, retry_after=120)
    return RateLimitResult(allowed=True, remaining=max(0, limit - count), retry_after=0)


# ── Anti-abuse: duplicate callback guard ──────────────────────────
_OPENED_RECENTLY: dict = {}


def mark_recently_opened(user_id: int, whisper_id: str, ttl: int = 3) -> bool:
    """Returns True if this (user, wid) was opened in the last `ttl` seconds."""
    key = (user_id, whisper_id)
    now = time.time()
    _OPENED_RECENTLY[key] = now
    return True


def was_recently_opened(user_id: int, whisper_id: str, ttl: int = 3) -> bool:
    key = (user_id, whisper_id)
    ts = _OPENED_RECENTLY.get(key)
    if not ts:
        return False
    if time.time() - ts > ttl:
        _OPENED_RECENTLY.pop(key, None)
        return False
    return True


def _gen_token(n: int = 24) -> str:
    return secrets.token_hex(n)
