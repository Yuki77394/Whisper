"""WhisperX – small helper functions."""
from __future__ import annotations

import html
import time
from typing import Optional


def now_ts() -> int:
    return int(time.time())


def truncate(text: str, n: int = 80) -> str:
    if not text:
        return ""
    text = text.strip().replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


def humanize_preview(text: str, n: int = 60) -> str:
    """Return a single-line, html-escaped preview for cards."""
    if not text:
        return ""
    one_line = " ".join(text.split())
    if len(one_line) > n:
        one_line = one_line[: n - 1] + "…"
    return html.escape(one_line)


def display_name(first: str = "", last: str = "", username: str = "") -> str:
    """Best-effort display name."""
    name = (first or "").strip()
    if last:
        name = (name + " " + last.strip()).strip()
    if not name:
        uname = (username or "").lstrip("@").strip()
        name = f"@{uname}" if uname else "Unknown"
    return name


def safe_mention(first: str = "", user_id: Optional[int] = None, username: str = "") -> str:
    """
    Return a Telegram-friendly mention.
    Prefer @username; fall back to tg://user?id= link.
    """
    uname = (username or "").lstrip("@").strip()
    if uname:
        return f"@{uname}"
    if user_id:
        name = (first or "").strip() or "User"
        return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'
    return html.escape(first or "Unknown")


def parse_expiry_label(label: str) -> Optional[int]:
    """Convert '5m','1h','24h','7d' style labels to seconds."""
    label = (label or "").strip().lower()
    if not label or label == "never" or label == "off":
        return None
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    if label[-1] in units and label[:-1].isdigit():
        return int(label[:-1]) * units[label[-1]]
    # named presets
    presets = {
        "5min": 300, "10min": 600, "30min": 1800,
        "1hour": 3600, "24hours": 86400, "7days": 604800,
    }
    return presets.get(label)


def fmt_time_short(ts: Optional[int]) -> str:
    if not ts:
        return "—"
    return time.strftime("%H:%M", time.gmtime(ts))


def fmt_time_full(ts: Optional[int]) -> str:
    if not ts:
        return "—"
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(ts))
