"""
WhisperX – admin log group writer.

Sends structured log messages to LOG_GROUP_ID. Respects METADATA_ONLY_LOGS:
when true, only metadata is logged (no message text or captions).

Errors are NEVER silently swallowed — every send failure is logged with
full context (error type, chat_id, message) so the operator can diagnose
configuration issues (wrong LOG_GROUP_ID, bot not a member, missing
permissions, etc.).
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

    async def verify_connectivity(self) -> bool:
        """Test that the bot can send messages to the log group.

        Called once at startup. Returns True if the test succeeded.
        Logs a clear error if not.

        CRITICAL for Heroku/in_memory sessions: Pyrogram needs to know
        the access_hash for a chat before it can send messages to it by
        numeric ID. On ephemeral filesystems (Heroku), the session has
        no cached peers, so `send_message(chat_id=-100...)` fails with
        `ValueError: Peer id invalid`. Calling `get_chat()` first forces
        Pyrogram to fetch and cache the access_hash from Telegram.
        """
        if not self.enabled:
            log.warning(
                "[LOG_GROUP] LOG_GROUP_ID is not set — whisper logging is DISABLED. "
                "Set LOG_GROUP_ID to enable audit logs."
            )
            return False

        # Step 1: Resolve the chat (caches access_hash in the session)
        try:
            chat = await self.client.get_chat(self.chat_id)
            log.info(
                "[LOG_GROUP] resolved chat: id=%s type=%s title=%s",
                chat.id, chat.type, getattr(chat, "title", "—"),
            )
        except Exception as e:
            log.error(
                "[LOG_GROUP] CANNOT RESOLVE log group (chat_id=%s): %s: %s\n"
                "Possible causes:\n"
                "  1. Bot is not a member of the group/channel\n"
                "  2. LOG_GROUP_ID is wrong (must be the numeric chat id, "
                "e.g. -1001234567890 for supergroups)\n"
                "  3. The group/channel doesn't exist\n"
                "Whisper logging will NOT work until this is fixed.",
                self.chat_id, type(e).__name__, e,
            )
            return False

        # Step 2: Try sending a test message
        try:
            await self.client.send_message(
                chat_id=self.chat_id,
                text="🟢 <b>WhisperX log group connected.</b>\n\n"
                     "Whisper creation/opening events will be logged here.",
                disable_web_page_preview=True,
            )
            log.info("[LOG_GROUP] connectivity verified — chat_id=%s", self.chat_id)
            return True
        except Exception as e:
            log.error(
                "[LOG_GROUP] CANNOT SEND to log group (chat_id=%s): %s: %s\n"
                "Possible causes:\n"
                "  1. Bot lacks send permission in that chat\n"
                "  2. Bot was kicked/removed after startup\n"
                "  3. Chat is read-only (channel where bot isn't admin)\n"
                "Whisper logging will NOT work until this is fixed.",
                self.chat_id, type(e).__name__, e,
            )
            return False

    async def _safe_send(self, text: str, *, event: str = "", whisper_id: str = "") -> None:
        """Send a log message. Never raises — logs full error on failure.

        If the first send attempt fails with 'Peer id invalid' (Pyrogram
        lost the access_hash, common on in-memory sessions), retry once
        after re-resolving the chat via get_chat().
        """
        if not self.enabled:
            return
        try:
            await self.client.send_message(
                chat_id=self.chat_id,
                text=text,
                disable_web_page_preview=True,
            )
            return
        except Exception as e:
            err_str = str(e)
            # Pyrogram loses access_hash on in-memory sessions — re-resolve
            if "Peer id invalid" in err_str or "PEER_ID_INVALID" in err_str.upper():
                log.warning(
                    "[LOG_GROUP] peer cache miss — re-resolving chat_id=%s and retrying",
                    self.chat_id,
                )
                try:
                    await self.client.get_chat(self.chat_id)
                    await self.client.send_message(
                        chat_id=self.chat_id,
                        text=text,
                        disable_web_page_preview=True,
                    )
                    return
                except Exception as e2:
                    log.error(
                        "[LOG_GROUP] send FAILED after retry (event=%s whisper_id=%s "
                        "chat_id=%s): %s: %s",
                        event, whisper_id, self.chat_id,
                        type(e2).__name__, e2,
                    )
                    return
            # Other error — log full context
            log.error(
                "[LOG_GROUP] send FAILED (event=%s whisper_id=%s chat_id=%s): "
                "%s: %s",
                event, whisper_id, self.chat_id,
                type(e).__name__, e,
            )

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
            f"  Resolved IDs: <code>{whisper_doc.get('recipient_ids', [])}</code>",
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

        await self._safe_send(
            "\n".join(body_lines),
            event="create",
            whisper_id=whisper_doc.get("whisper_id", ""),
        )

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
        await self._safe_send(text, event="opened", whisper_id=whisper_id)

    # ── EXPIRED ─────────────────────────────────────────────────────
    async def log_expired(self, *, whisper_id: str) -> None:
        if not self.enabled:
            return
        text = (
            "⏳ <b>WHISPER EXPIRED</b>\n\n"
            f"<b>Whisper ID:</b> <code>{whisper_id}</code>\n"
        )
        await self._safe_send(text, event="expired", whisper_id=whisper_id)

    # ── DELETED (manual) ────────────────────────────────────────────
    async def log_deleted(self, *, whisper_id: str, by_user_id: int) -> None:
        if not self.enabled:
            return
        text = (
            "🗑 <b>WHISPER DELETED</b>\n\n"
            f"<b>Whisper ID:</b> <code>{whisper_id}</code>\n"
            f"<b>By user:</b> <code>{by_user_id}</code>\n"
        )
        await self._safe_send(text, event="deleted", whisper_id=whisper_id)
