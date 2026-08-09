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
    InlineKeyboardButton,
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
        log.info("[WHISPER_CREATE] type=public sender_id=%s content_len=%d",
                  user.id, len(parsed.content))
        try:
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
        except Exception as e:
            log.exception("[WHISPER_DB_INSERT_FAILED] type=public sender_id=%s error=%s", user.id, e)
            results.append(
                InlineQueryResultArticle(
                    id="error",
                    title="❌ Failed to create whisper",
                    description="Database error. Please try again.",
                    input_message_content=InputTextMessageContent(
                        "❌ <b>Failed to create whisper.</b>\n\nPlease try again in a moment."
                    ),
                )
            )
            await inline_query.answer(results, cache_time=0)
            return

        # Verify the whisper actually exists in MongoDB before showing success
        verified = await WhispersDB.get(doc["whisper_id"])
        if not verified:
            log.error("[WHISPER_DB_VERIFY_FAILED] whisper_id=%s not found after insert", doc["whisper_id"])
            results.append(
                InlineQueryResultArticle(
                    id="error",
                    title="❌ Failed to create whisper",
                    description="Database verification failed.",
                    input_message_content=InputTextMessageContent(
                        "❌ <b>Failed to create whisper.</b>\n\nDatabase verification failed."
                    ),
                )
            )
            await inline_query.answer(results, cache_time=0)
            return

        log.info("[WHISPER_DB_INSERTED] whisper_id=%s type=public sender_id=%s",
                  doc["whisper_id"], user.id)
        log.info("[WHISPER_BUTTON] whisper_id=%s callback_data=op:%s",
                  doc["whisper_id"], doc["whisper_id"])

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

    log.info("[WHISPER_CREATE] type=private sender_id=%s recipient_handles=%s recipient_ids=%s content_len=%d",
              user.id, parsed.recipient_handles, parsed.recipient_ids, len(parsed.content))

    try:
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
    except Exception as e:
        log.exception("[WHISPER_DB_INSERT_FAILED] type=private sender_id=%s error=%s", user.id, e)
        results.append(
            InlineQueryResultArticle(
                id="error",
                title="❌ Failed to create whisper",
                description="Database error. Please try again.",
                input_message_content=InputTextMessageContent(
                    "❌ <b>Failed to create whisper.</b>\n\nPlease try again in a moment."
                ),
            )
        )
        await inline_query.answer(results, cache_time=0)
        return

    # Verify the whisper actually exists in MongoDB before showing success
    verified = await WhispersDB.get(doc["whisper_id"])
    if not verified:
        log.error("[WHISPER_DB_VERIFY_FAILED] whisper_id=%s not found after insert", doc["whisper_id"])
        results.append(
            InlineQueryResultArticle(
                id="error",
                title="❌ Failed to create whisper",
                description="Database verification failed.",
                input_message_content=InputTextMessageContent(
                    "❌ <b>Failed to create whisper.</b>\n\nDatabase verification failed."
                ),
            )
        )
        await inline_query.answer(results, cache_time=0)
        return

    log.info("[WHISPER_DB_INSERTED] whisper_id=%s type=private sender_id=%s resolved_recipient_ids=%s",
              doc["whisper_id"], user.id, doc.get("recipient_ids", []))
    log.info("[WHISPER_BUTTON] whisper_id=%s callback_data=op:%s",
              doc["whisper_id"], doc["whisper_id"])

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

    await inline_query.answer(results, cache_time=config.inline_cache_seconds)
