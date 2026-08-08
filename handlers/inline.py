"""
WhisperX – inline query handler.

This is the core UX. The user types:

    @BotUsername @target Hello

or:

    @BotUsername Hello @target

…and gets an inline result card. When sent into a chat, the result
becomes a protected whisper that only @target (or the replied user)
can open.
"""
from __future__ import annotations

import html
import logging
from typing import List

from pyrogram import filters
from pyrogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
)

from config import config
from database.users import UsersDB
from database.whispers import WhispersDB
from services.parser import parse_whisper_input
from services.whisper import WhisperService
from services.logger import LogService
from utils.helpers import humanize_preview, truncate, now_ts
from utils.formatting import (
    fmt_whisper_card,
    fmt_inline_result_title,
    fmt_inline_result_desc,
)
from utils.security import rate_limit_check
from keyboards.settings import whisper_open_kb

log = logging.getLogger(__name__)

# Injected in register()
whisper_service: WhisperService = None  # type: ignore[assignment]
log_service: LogService = None  # type: ignore[assignment]
_bot_username: str = ""


def register(app, *, whisper_svc: WhisperService, log_svc: LogService) -> None:
    global whisper_service, log_service, _bot_username
    whisper_service = whisper_svc
    log_service = log_svc

    @app.on_inline_query()
    async def _inline_handler(client, inline_query: InlineQuery):
        await _handle_inline(client, inline_query)


async def _handle_inline(client, inline_query: InlineQuery) -> None:
    user = inline_query.from_user
    if not user:
        return

    # Banned?
    if await UsersDB.is_banned(user.id):
        await inline_query.answer(
            [
                InlineQueryResultArticle(
                    id="banned",
                    title="🚫 You are banned",
                    description="Contact the bot administrator.",
                    input_message_content=InputTextMessageContent(
                        "🚫 You are banned from using this bot."
                    ),
                )
            ],
            cache_time=0,
        )
        return

    # Rate limit
    rl = await rate_limit_check(user.id, key="inline")
    if not rl.allowed:
        await inline_query.answer(
            [
                InlineQueryResultArticle(
                    id="rate",
                    title="⏳ Slow down",
                    description=f"Retry in {rl.retry_after}s.",
                    input_message_content=InputTextMessageContent(
                        "⏳ You're sending whispers too fast. Please wait a moment."
                    ),
                )
            ],
            cache_time=0,
        )
        return

    # Persist user (so usernames are searchable later)
    await UsersDB.upsert(
        user_id=user.id,
        first_name=user.first_name or "",
        last_name=user.last_name or "",
        username=user.username or "",
    )

    # Discover bot username (cached on first call)
    global _bot_username
    if not _bot_username:
        me = await client.get_me()
        _bot_username = (me.username or "").lstrip("@")

    raw_query = inline_query.query or ""
    # Reply target if any (works in groups where the user replied then
    # invoked the bot inline — Pyrogram exposes this only via the
    # `inline_message_id` flow; for replied messages in groups, the
    # user must use the textual form).
    replied_handle = None
    replied_id = None

    parsed = parse_whisper_input(
        raw_query,
        bot_username=_bot_username,
        replied_recipient=replied_handle,
        replied_recipient_id=replied_id,
    )

    results = []

    if parsed.error or not parsed.content and not parsed.is_public:
        # Empty or invalid — show a help card
        results.append(
            InlineQueryResultArticle(
                id="help",
                title="✍️ WhisperX",
                description="Type: @username message  •  or  •  message @username",
                input_message_content=InputTextMessageContent(
                    "🔒 <b>WhisperX</b>\n\n"
                    "Type your whisper in the format:\n"
                    "<code>@BotUsername @target Hello</code>\n\n"
                    "or\n\n"
                    "<code>@BotUsername Hello @target</code>",
                ),
                reply_markup=InlineKeyboardMarkup(
                    [[InlineKeyboardButton("✍️ Open WhisperX",
                      switch_inline_query_current_chat="")]]
                ),
            )
        )
        await inline_query.answer(results, cache_time=10)
        return

    # Public whisper (no recipient) — anyone can open
    if parsed.is_public:
        preview = humanize_preview(parsed.content, 60)
        doc = await whisper_service.create_text_whisper(
            sender_id=user.id,
            sender_first=user.first_name or "",
            sender_last=user.last_name or "",
            sender_username=user.username or "",
            recipient_handles=[],
            recipient_ids=[],
            content=parsed.content,
            expires_at=None,
            is_one_time=False,
            is_anonymous=False,
        )
        results.append(
            InlineQueryResultArticle(
                id=f"pub_{doc['whisper_id']}",
                title="📖 Public Whisper",
                description=fmt_inline_result_desc(preview, None, []),
                input_message_content=InputTextMessageContent(
                    fmt_whisper_card(
                        recipient_handles=[],
                        media_type=None,
                        is_anonymous=False,
                        is_one_time=False,
                        expires_at=None,
                    ),
                    disable_web_page_preview=True,
                ),
                reply_markup=whisper_open_kb(doc["whisper_id"]),
            )
        )
        await inline_query.answer(results, cache_time=config.inline_cache_seconds)
        return

    # Private whisper
    preview = humanize_preview(parsed.content, 60)
    expires_at = (now_ts() + config.default_expiry_seconds) if config.default_expiry_seconds else None

    doc = await whisper_service.create_text_whisper(
        sender_id=user.id,
        sender_first=user.first_name or "",
        sender_last=user.last_name or "",
        sender_username=user.username or "",
        recipient_handles=parsed.recipient_handles,
        recipient_ids=parsed.recipient_ids,
        content=parsed.content,
        expires_at=expires_at,
        is_one_time=False,
        is_anonymous=False,
    )

    title = fmt_inline_result_title(parsed.recipient_handles)
    desc = fmt_inline_result_desc(preview, None, parsed.recipient_handles)

    results.append(
        InlineQueryResultArticle(
            id=f"priv_{doc['whisper_id']}",
            title=title,
            description=desc,
            input_message_content=InputTextMessageContent(
                fmt_whisper_card(
                    recipient_handles=parsed.recipient_handles,
                    media_type=None,
                    is_anonymous=False,
                    is_one_time=False,
                    expires_at=expires_at,
                ),
                disable_web_page_preview=True,
            ),
            reply_markup=whisper_open_kb(doc["whisper_id"]),
        )
    )

    # Optional second card: one-time variant of the same whisper
    # (Create a second whisper so the recipient can't open both)
    # Disabled by default to keep things simple — uncomment to enable.

    await inline_query.answer(results, cache_time=config.inline_cache_seconds)
