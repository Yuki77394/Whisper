"""WhisperX – user-facing text formatting helpers."""
from __future__ import annotations

import html
from typing import Optional


def fmt_whisper_card(
    *,
    recipient_handles: list,
    media_type: Optional[str],
    is_anonymous: bool,
    is_one_time: bool,
    expires_at: Optional[int],
) -> str:
    """Card shown when the whisper is sent into a chat (before opening)."""
    recipients = ", ".join(f"@{h}" for h in recipient_handles) or "Recipient"

    media_tag = ""
    if media_type:
        media_tag = f"  📎 {media_type.upper()}"

    flags = []
    if is_anonymous:
        flags.append("👤 Anonymous")
    if is_one_time:
        flags.append("🔥 One-Time")
    if expires_at:
        flags.append("⏳ Timed")
    flag_str = ("  •  " + "  •  ".join(flags)) if flags else ""

    return (
        f"🔒 <b>Private Whisper</b>{media_tag}{flag_str}\n\n"
        f"Only <b>{html.escape(recipients)}</b> can open this whisper.\n\n"
        f"<i>Telegram can't prevent screenshots or photos of the screen.</i>"
    )


def fmt_opened_text(content: str, media_type: Optional[str], caption: str = "") -> str:
    """Shown to the recipient when they successfully open the whisper."""
    if media_type:
        head = "💌 <b>Whisper</b>"
        body = ""
        if caption:
            body = f"\n\n{html.escape(caption)}"
        return f"{head}{body}"
    return f"💌 <b>Whisper</b>\n\n{html.escape(content)}"


def fmt_wrong_user(recipient_handles: list) -> str:
    recipients = ", ".join(f"@{h}" for h in recipient_handles) or "the recipient"
    return (
        "❌ <b>This whisper isn't for you.</b>\n\n"
        f"Only <b>{html.escape(recipients)}</b> can open this whisper."
    )


def fmt_expired() -> str:
    return "⏳ <b>This whisper has expired.</b>\n\nThe content has been permanently removed."


def fmt_consumed() -> str:
    return "✅ <b>This whisper has already been opened.</b>\n\nOne-time whispers cannot be reopened."


def fmt_inline_result_title(recipient_handles: list) -> str:
    if not recipient_handles:
        return "📖 Public Whisper"
    return f"🔒 Whisper to @{recipient_handles[0]}"


def fmt_inline_result_desc(
    preview: str, media_type: Optional[str], recipient_handles: list
) -> str:
    bits = []
    if media_type:
        bits.append(f"📎 {media_type.upper()}")
    if preview:
        bits.append(f'"{preview}"')
    if recipient_handles:
        bits.append(f"Only @{recipient_handles[0]} can open")
    return "  •  ".join(bits) if bits else "Send a private whisper"
