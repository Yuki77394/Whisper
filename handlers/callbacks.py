"""
WhisperX – callback query handler.

Validates & opens whispers, manages history navigation, deletion, etc.

Security rules enforced for every "Open Whisper" press:
  1. Whisper exists
  2. Whisper not expired
  3. User is an authorised recipient
  4. Whisper not already consumed (if one-time)
  5. Callback payload is well-formed
"""
from __future__ import annotations

import html
import logging
from typing import Optional

from pyrogram import filters
from pyrogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from config import config
from database.whispers import WhispersDB
from database.history import HistoryDB
from database.users import UsersDB
from services.whisper import WhisperService
from services.media import send_media_to_user
from services.logger import LogService
from utils.helpers import now_ts, display_name, fmt_time_short, truncate, humanize_preview
from utils.security import unsign_callback, was_recently_opened, mark_recently_opened
from utils.formatting import (
    fmt_whisper_card, fmt_opened_text, fmt_wrong_user, fmt_expired, fmt_consumed,
)
from keyboards.settings import (
    whisper_open_kb, close_only_kb,
    history_nav_kb, history_item_kb,
)

log = logging.getLogger(__name__)

# Injected
whisper_service: WhisperService = None  # type: ignore
log_service: LogService = None  # type: ignore


def register(app, *, whisper_svc: WhisperService, log_svc: LogService) -> None:
    global whisper_service, log_service
    whisper_service = whisper_svc
    log_service = log_svc

    @app.on_callback_query(filters.regex(r"^op:[a-f0-9]{24}$"))
    async def _open_whisper(_, query: CallbackQuery):
        await _handle_open(query)

    @app.on_callback_query(filters.regex(r"^vw:[a-f0-9]{24}$"))
    async def _view_history_item(_, query: CallbackQuery):
        await _handle_history_view(query)

    @app.on_callback_query(filters.regex(r"^del:[a-f0-9]{24}$"))
    async def _delete_history_item(_, query: CallbackQuery):
        await _handle_history_delete(query)

    @app.on_callback_query(filters.regex(r"^hist:(\d+):(sent|received)$"))
    async def _history_page(_, query: CallbackQuery):
        await _handle_history_page(query)


# ── Open whisper ──────────────────────────────────────────────────
async def _handle_open(query: CallbackQuery) -> None:
    user = query.from_user
    if not user:
        await query.answer("❌ Cannot identify user.", show_alert=True)
        return

    log.info("[WHISPER_CALLBACK] from_user_id=%s username=%s callback_data=%s",
              user.id, user.username, query.data)

    parsed = unsign_callback(query.data or "")
    if not parsed:
        log.warning("[WHISPER_CALLBACK] invalid callback_data=%s from user=%s", query.data, user.id)
        await query.answer("❌ Invalid request.", show_alert=True)
        return
    _, wid = parsed

    log.info("[WHISPER_OPEN_ATTEMPT] whisper_id=%s requester_id=%s requester_username=%s",
              wid, user.id, user.username)

    # Duplicate-click guard (Telegram sometimes fires twice)
    if was_recently_opened(user.id, wid, ttl=2):
        await query.answer()
        return
    mark_recently_opened(user.id, wid)

    whisper = await WhispersDB.get(wid)
    if not whisper or whisper.get("status") == "deleted":
        log.warning("[WHISPER_OPEN_ATTEMPT] whisper_id=%s not found or deleted", wid)
        await _safe_edit(query, "🗑 <b>This whisper has been deleted.</b>", close_only_kb())
        await query.answer()
        return

    # Expired?
    if whisper.get("expires_at") and whisper["expires_at"] <= now_ts():
        log.info("[WHISPER_OPEN_ATTEMPT] whisper_id=%s expired", wid)
        await WhispersDB.mark_expired(wid)
        await HistoryDB.update_status(wid, "expired")
        await log_service.log_expired(whisper_id=wid)
        await _safe_edit(query, fmt_expired(), close_only_kb())
        await query.answer("Expired", show_alert=False)
        return

    # Already opened + one-time?
    is_one_time = whisper.get("is_one_time", False)
    already_opened_by_me = await WhispersDB.is_opened_by(wid, user.id)

    if is_one_time and already_opened_by_me:
        log.info("[WHISPER_OPEN_ATTEMPT] whisper_id=%s already opened by user=%s (one-time)", wid, user.id)
        await _safe_edit(query, fmt_consumed(), close_only_kb())
        await query.answer("Already opened", show_alert=False)
        return

    if is_one_time and whisper.get("opened_by"):
        log.info("[WHISPER_OPEN_ATTEMPT] whisper_id=%s already consumed by another user (one-time)", wid)
        await _safe_edit(query, fmt_consumed(), close_only_kb())
        await query.answer("Already opened", show_alert=False)
        return

    # Authorised? Pass username for username-based fallback auth.
    allowed = await WhispersDB.can_open(wid, user.id, username=user.username or "")
    log.info("[WHISPER_AUTH] whisper_id=%s user_id=%s username=%s authorized=%s",
              wid, user.id, user.username, allowed)

    if not allowed:
        await query.answer(
            "❌ This whisper isn't for you.",
            show_alert=True,
        )
        # Edit the message text to make the denial persistent
        try:
            await query.message.edit_text(
                fmt_wrong_user(whisper.get("recipient_handles", [])),
                reply_markup=close_only_kb(),
            )
        except Exception:
            pass
        return

    # ── Authorized: reveal content ─────────────────────────────────
    first_open = await WhispersDB.mark_opened(wid, user.id)
    log.info("[WHISPER_OPENED] whisper_id=%s user_id=%s first_open=%s",
              wid, user.id, first_open)
    if first_open:
        await HistoryDB.update_status(wid, "opened")
        try:
            await log_service.log_opened(
                whisper_id=wid,
                opened_by_id=user.id,
                opened_by_name=display_name(
                    user.first_name, user.last_name, user.username or ""
                ),
            )
            log.info("[WHISPER_LOGGED] whisper_id=%s event=opened user_id=%s", wid, user.id)
        except Exception as e:
            log.exception("[WHISPER_LOG_FAILED] whisper_id=%s event=opened error=%s", wid, e)

    media_type = whisper.get("media_type")
    file_ids = whisper.get("media_file_ids", []) or []
    content = whisper.get("content", "") or ""
    caption = whisper.get("caption", "") or ""

    # For media whispers we keep the card and try to send the media
    # directly to the user via the bot private chat (best-effort).
    if media_type and file_ids:
        # Edit the inline card to a confirmation
        await _safe_edit(
            query,
            "✅ <b>Whisper opened.</b>\n\n"
            "Check your private chat with the bot for the media.\n"
            "<i>If you have never started the bot in private, the media cannot be delivered.</i>",
            close_only_kb(),
        )
        await query.answer("Opened ✓", show_alert=False)

        # Try to DM the media
        try:
            sent = await send_media_to_user(
                query.message._client,
                chat_id=user.id,
                media_type=media_type,
                file_ids=file_ids,
                caption=caption,
            )
            if not sent:
                await query.message._client.send_message(
                    chat_id=user.id,
                    text=(
                        "⚠️ The media attached to a whisper could not be "
                        "delivered (file_id expired). Please ask the sender "
                        "to re-send it."
                    ),
                )
        except Exception as e:  # noqa: BLE001
            log.warning("media DM failed: %s", e)
        return

    # Text-only whisper: edit the inline card to show content
    await _safe_edit(
        query,
        fmt_opened_text(content, media_type=None),
        close_only_kb(),
    )
    await query.answer("Opened ✓", show_alert=False)


# ── History view (private chat only) ──────────────────────────────
async def _handle_history_view(query: CallbackQuery) -> None:
    user = query.from_user
    parsed = unsign_callback(query.data or "")
    if not parsed:
        await query.answer("❌ Invalid request.", show_alert=True)
        return
    _, wid = parsed

    whisper = await WhispersDB.get(wid)
    if not whisper:
        await query.answer("Whisper not found.", show_alert=True)
        return

    if whisper.get("sender_id") != user.id and user.id not in (whisper.get("recipient_ids") or []):
        await query.answer("❌ Not yours.", show_alert=True)
        return

    if whisper.get("status") in ("deleted", "expired"):
        await query.answer("This whisper is no longer available.", show_alert=True)
        return

    media_type = whisper.get("media_type")
    content = whisper.get("content", "") or ""
    caption = whisper.get("caption", "") or ""
    recipients = ", ".join(f"@{h}" for h in whisper.get("recipient_handles", [])) or "—"
    created = fmt_time_short(whisper.get("created_at"))
    status = whisper.get("status", "—").capitalize()

    text = (
        f"📜 <b>Whisper Detail</b>\n\n"
        f"<b>ID:</b> <code>{wid}</code>\n"
        f"<b>To:</b> {html.escape(recipients)}\n"
        f"<b>Created:</b> {created}\n"
        f"<b>Status:</b> {status}\n"
    )
    if media_type:
        text += f"<b>Media:</b> {media_type.upper()}\n"
        if caption:
            text += f"<b>Caption:</b> {html.escape(truncate(caption, 200))}\n"
    else:
        text += f"\n<b>Content:</b>\n{html.escape(content)}\n"

    can_view = (whisper.get("sender_id") == user.id) or await WhispersDB.can_open(wid, user.id)
    can_delete = whisper.get("sender_id") == user.id
    await _safe_edit(query, text, history_item_kb(wid, can_delete=can_delete, can_view=can_view))
    await query.answer()


async def _handle_history_delete(query: CallbackQuery) -> None:
    user = query.from_user
    parsed = unsign_callback(query.data or "")
    if not parsed:
        await query.answer("❌ Invalid request.", show_alert=True)
        return
    _, wid = parsed

    whisper = await WhispersDB.get(wid)
    if not whisper:
        await query.answer("Whisper not found.", show_alert=True)
        return

    if whisper.get("sender_id") != user.id:
        await query.answer("❌ You can only delete your own whispers.", show_alert=True)
        return

    await WhispersDB.delete(wid)
    await HistoryDB.update_status(wid, "deleted")
    await log_service.log_deleted(whisper_id=wid, by_user_id=user.id)
    await _safe_edit(query, "🗑 <b>Whisper deleted.</b>", close_only_kb())
    await query.answer("Deleted ✓")


async def _handle_history_page(query: CallbackQuery) -> None:
    user = query.from_user
    parts = (query.data or "").split(":")
    if len(parts) != 3:
        await query.answer()
        return
    try:
        page = int(parts[1])
    except ValueError:
        page = 1
    direction = parts[2] if parts[2] in {"sent", "received"} else "sent"

    res = await HistoryDB.list_paginated(user.id, page=page, per_page=5, direction=direction)
    items = res["items"]

    if not items:
        text = (
            f"📜 <b>Whisper History</b>\n\n"
            f"<i>No {direction} whispers yet.</i>"
        )
        await _safe_edit(query, text, history_nav_kb(1, 1, direction))
        await query.answer()
        return

    lines = [f"📜 <b>Whisper History</b> ({direction}) — page {res['page']}/{res['pages']}", ""]
    kb_rows = []
    for idx, it in enumerate(items, start=1):
        rec = ", ".join(f"@{h}" for h in it.get("recipient_handles", [])) or "—"
        preview = humanize_preview(it.get("preview", ""), 50)
        status = it.get("status", "—").capitalize()
        mtype = it.get("media_type")
        tag = f" [{mtype.upper()}]" if mtype else ""
        created = fmt_time_short(it.get("created_at"))
        lines.append(
            f"{idx}. <b>{html.escape(rec)}</b>{tag}\n"
            f'   "{html.escape(preview)}"\n'
            f"   Status: {status} • Created: {created}"
        )
        kb_rows.append([
            InlineKeyboardButton(f"{idx}. {status[:1]}", callback_data=f"vw:{it['whisper_id']}"),
            InlineKeyboardButton("🗑", callback_data=f"del:{it['whisper_id']}"),
        ])
    # Append nav
    nav_row = []
    if res["page"] > 1:
        nav_row.append(InlineKeyboardButton("⬅️", callback_data=f"hist:{res['page']-1}:{direction}"))
    nav_row.append(InlineKeyboardButton(f"{res['page']}/{res['pages']}", callback_data="noop"))
    if res["page"] < res["pages"]:
        nav_row.append(InlineKeyboardButton("➡️", callback_data=f"hist:{res['page']+1}:{direction}"))
    kb_rows.append(nav_row)
    kb_rows.append([
        InlineKeyboardButton("📤 Sent" if direction != "sent" else "📤 Sent ✓",
                             callback_data="hist:1:sent"),
        InlineKeyboardButton("📥 Received" if direction != "received" else "📥 Received ✓",
                             callback_data="hist:1:received"),
    ])
    kb_rows.append([InlineKeyboardButton("◀️ Back", callback_data="start")])

    await _safe_edit(query, "\n".join(lines), InlineKeyboardMarkup(kb_rows))
    await query.answer()


# ── helper: safe edit_text ────────────────────────────────────────
async def _safe_edit(query: CallbackQuery, text: str, kb: Optional[InlineKeyboardMarkup]) -> None:
    try:
        await query.message.edit_text(text, reply_markup=kb, disable_web_page_preview=True)
    except Exception as e:  # noqa: BLE001
        log.debug("edit_text failed: %s", e)
