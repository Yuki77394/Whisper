"""
WhisperX – admin log group writer.

Sends structured log messages to LOG_GROUP_ID. Respects METADATA_ONLY_LOGS:
when true, only metadata is logged (no message text or captions).
"""
from __future__ import annotations

import html
import logging
from typing import Optional, Any

from config import config
from utils.helpers import display_name, fmt_time_full

log = logging.getLogger(__name__)


class LogService:
    def __init__(self, client):
        self.client = client
        self.chat_id = config.log_group_id

    @property
    def enabled(self) -> bool:
        return bool(self.chat_id)

    async def _safe_send(self, text: str) -> None:
        if not self.enabled:
            return
        try:
            await self.client.send_message(
                chat_id=self.chat_id,
                text=text,
                disable_web_page_preview=True,
            )
        except Exception as e:  # noqa: BLE001
            log.warning("log group send failed: %s", e)

    # ── NEW WHISPER ─────────────────────────────────────────────────
    async def log_create(self, *, whisper_doc: dict, content_preview: str) -> None:
        if not self.enabled:
            return

        recipients = ", ".join(f"@{h}" for h in whisper_doc.get("recipient_handles", [])) or "—"
        media_type = whisper_doc.get("media_type") or "Text"

        body_lines = [
            "🆕 <b>NEW WHISPER</b>",
            "",
            f"<b>Whisper ID:</b> <code>{whisper_doc['whisper_id']}</code>",
            f"<b>Type:</b> {html.escape(str(media_type))}",
            f"<b>One-time:</b> {whisper_doc.get('is_one_time', False)}",
            f"<b>Anonymous:</b> {whisper_doc.get('is_anonymous', False)}",
            "",
            "<b>Sender:</b>",
            f"  Name: {html.escape(whisper_doc.get('sender_name', '—'))}",
            f"  Telegram ID: <code>{whisper_doc.get('sender_id', '—')}</code>",
            "",
            "<b>Recipient:</b>",
            f"  {html.escape(recipients)}",
            "",
            f"<b>Created:</b> {fmt_time_full(whisper_doc.get('created_at'))}",
            f"<b>Status:</b> Unopened",
        ]

        if not config.metadata_only_logs:
            body_lines.extend([
                "",
                f"<b>Message preview:</b>",
                f"<i>{html.escape(content_preview or '(media only)')}</i>",
            ])

        await self._safe_send("\n".join(body_lines))

    # ── OPENED ──────────────────────────────────────────────────────
    async def log_opened(self, *, whisper_id: str, opened_by_id: int, opened_by_name: str) -> None:
        if not self.enabled:
            return
        from utils.helpers import now_ts
        text = (
            "✅ <b>WHISPER OPENED</b>\n\n"
            f"<b>Whisper ID:</b> <code>{whisper_id}</code>\n"
            f"<b>Opened by:</b> {html.escape(opened_by_name)} "
            f"(<code>{opened_by_id}</code>)\n"
            f"<b>Opened at:</b> {fmt_time_full(now_ts())}\n"
        )
        await self._safe_send(text)

    # ── EXPIRED ─────────────────────────────────────────────────────
    async def log_expired(self, *, whisper_id: str) -> None:
        if not self.enabled:
            return
        text = (
            "⏳ <b>WHISPER EXPIRED</b>\n\n"
            f"<b>Whisper ID:</b> <code>{whisper_id}</code>\n"
        )
        await self._safe_send(text)

    # ── DELETED (manual) ────────────────────────────────────────────
    async def log_deleted(self, *, whisper_id: str, by_user_id: int) -> None:
        if not self.enabled:
            return
        text = (
            "🗑 <b>WHISPER DELETED</b>\n\n"
            f"<b>Whisper ID:</b> <code>{whisper_id}</code>\n"
            f"<b>By user:</b> <code>{by_user_id}</code>\n"
        )
        await self._safe_send(text)
