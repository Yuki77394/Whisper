"""
WhisperX – private-chat command handlers.

Includes:
  /history, /privacy, /settings, /language, /cancel
  /create  – advanced multi-step whisper creation
  Media ingestion in private chat (text, photo, video, voice, ...)
"""
from __future__ import annotations

import html
import logging
from typing import Optional, Dict, Any

from pyrogram import filters
from pyrogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from config import config
from database.users import UsersDB
from database.whispers import WhispersDB
from database.history import HistoryDB
from database.mongo import db
from services.whisper import WhisperService
from services.media import detect_media_type, extract_media
from services.logger import LogService
from utils.helpers import now_ts, display_name, truncate, fmt_time_short
from keyboards.start import start_kb
from keyboards.settings import (
    privacy_kb, language_kb, settings_kb, history_nav_kb, history_item_kb,
    create_flow_kb,
)

log = logging.getLogger(__name__)

# In-memory + DB-backed state for /create (auto-expires after 30 min idle).
CREATE_TIMEOUT = 1800

whisper_service: WhisperService = None  # type: ignore
log_service: LogService = None  # type: ignore


def register(app, *, whisper_svc: WhisperService, log_svc: LogService) -> None:
    global whisper_service, log_service
    whisper_service = whisper_svc
    log_service = log_svc

    # ── Plain commands ────────────────────────────────────────────
    @app.on_message(filters.command("history"))
    async def _history_cmd(_, message: Message):
        await _show_history(message, page=1, direction="sent")

    @app.on_message(filters.command("privacy"))
    async def _privacy_cmd(_, message: Message):
        cur = await UsersDB.get_privacy_mode(message.from_user.id)
        await message.reply_text(_PRIVACY_TEXT, reply_markup=privacy_kb(cur),
                                 disable_web_page_preview=True)

    @app.on_message(filters.command("settings"))
    async def _settings_cmd(_, message: Message):
        await message.reply_text("⚙️ <b>Settings</b>", reply_markup=settings_kb(),
                                 disable_web_page_preview=True)

    @app.on_message(filters.command("language"))
    async def _language_cmd(_, message: Message):
        user = await UsersDB.get(message.from_user.id) or {}
        await message.reply_text("🌐 <b>Language</b>",
                                 reply_markup=language_kb(user.get("language", "en")),
                                 disable_web_page_preview=True)

    @app.on_message(filters.command("cancel"))
    async def _cancel_cmd(_, message: Message):
        st = await _load_state(message.from_user.id)
        if st:
            await _clear_state(message.from_user.id)
            await message.reply_text("❌ Current whisper creation cancelled.")
        else:
            await message.reply_text("Nothing to cancel.")

    @app.on_message(filters.command("create"))
    async def _create_cmd(_, message: Message):
        await _upsert(message)
        await _set_state(message.from_user.id, {"step": "recipient"})
        await message.reply_text(
            "🛠 <b>Advanced Whisper Builder</b>\n\n"
            "<b>Step 1 — Recipient</b>\n\n"
            "Send the recipient's <b>@username</b> or numeric Telegram ID "
            "(prefix with <code>#id</code>, e.g. <code>#id123456789</code>).",
            reply_markup=create_flow_kb("recipient"),
        )

    # ── /create callback flow ─────────────────────────────────────
    @app.on_callback_query(filters.regex(r"^create(:[a-z0-9_]+(:[a-z0-9]+)?)?$"))
    async def _create_cb(_, query: CallbackQuery):
        await _handle_create_callback(query)

    # ── Plain-text / media ingestion during /create ───────────────
    @app.on_message(filters.private & ~filters.command(
        ["start", "help", "create", "history", "privacy", "settings",
         "language", "cancel", "stats", "users", "broadcast", "ban",
         "unban", "logs", "maintenance"]
    ))
    async def _private_input(_, message: Message):
        await _handle_create_input(message)


# ──────────────────────────────────────────────────────────────────
PRIVACY_TEXT = (
    "🔐 <b>Privacy Mode</b>\n\n"
    "<b>When enabled:</b>\n"
    "• Opening a whisper minimises extra metadata leaks\n"
    "• Sender info is hidden where the inline card already conveys enough\n"
    "• Stored personal data is reduced where technically possible\n\n"
    "<b>What WhisperX actually stores:</b>\n"
    "• Your Telegram user ID, name, username\n"
    "• The whisper content + media <code>file_id</code> until expiry or deletion\n"
    "• Open / expire timestamps for audit\n\n"
    "<b>Honest Telegram limitations:</b>\n"
    "• Telegram bots cannot prevent screenshots or external photos\n"
    "• Protected content only disables forwarding inside Telegram\n"
    "• Anonymity cannot be technically guaranteed beyond what the API exposes\n"
)


# ── /create state helpers (DB-backed) ─────────────────────────────
async def _load_state(user_id: int) -> Optional[Dict[str, Any]]:
    return await db.create_state.find_one({"user_id": user_id})  # type: ignore[union-attr]


async def _set_state(user_id: int, state: Dict[str, Any]) -> None:
    state["user_id"] = user_id
    state["updated_at"] = now_ts()
    await db.create_state.update_one(  # type: ignore[union-attr]
        {"user_id": user_id},
        {"$set": state},
        upsert=True,
    )


async def _clear_state(user_id: int) -> None:
    await db.create_state.delete_one({"user_id": user_id})  # type: ignore[union-attr]


async def _upsert(message: Message) -> None:
    u = message.from_user
    if not u:
        return
    await UsersDB.upsert(
        user_id=u.id,
        first_name=u.first_name or "",
        last_name=u.last_name or "",
        username=u.username or "",
    )


# ── /create callback router ───────────────────────────────────────
async def _handle_create_callback(query: CallbackQuery) -> None:
    parts = (query.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "cancel":
        await _clear_state(query.from_user.id)
        await query.message.edit_text("❌ Whisper creation cancelled.",
                                      reply_markup=start_kb())
        await query.answer("Cancelled")
        return

    if action == "recipient":
        await _set_state(query.from_user.id, {"step": "recipient",
                                              "recipient_handles": [],
                                              "recipient_ids": [],
                                              "content": "",
                                              "media_type": None,
                                              "media_file_ids": [],
                                              "caption": "",
                                              "expires_at": None,
                                              "is_one_time": False,
                                              "is_anonymous": False})
        await query.message.edit_text(
            "🛠 <b>Step 1 — Recipient</b>\n\n"
            "Send the recipient's <b>@username</b> or "
            "<code>#id123456789</code>.",
            reply_markup=create_flow_kb("recipient"),
        )
        await query.answer()
        return

    if action == "message":
        st = await _load_state(query.from_user.id)
        if not st or not (st.get("recipient_handles") or st.get("recipient_ids")):
            await query.answer("Add a recipient first.", show_alert=True)
            return
        st["step"] = "message"
        await _set_state(query.from_user.id, st)
        await query.message.edit_text(
            "🛠 <b>Step 2 — Message</b>\n\n"
            "Type your whisper text now.\n"
            "Or send a media item (photo / video / voice / ...).",
            reply_markup=create_flow_kb("message"),
        )
        await query.answer()
        return

    if action == "media":
        st = await _load_state(query.from_user.id)
        if not st:
            await query.answer("Session expired.", show_alert=True)
            return
        st["step"] = "media"
        await _set_state(query.from_user.id, st)
        await query.message.edit_text(
            "🛠 <b>Step 3 — Media (optional)</b>\n\n"
            "Send a photo / video / voice / audio / document / GIF / sticker.\n"
            "Press <b>Done</b> when finished.",
            reply_markup=create_flow_kb("media"),
        )
        await query.answer()
        return

    if action == "expiry":
        st = await _load_state(query.from_user.id)
        if not st:
            await query.answer("Session expired.", show_alert=True)
            return
        if not st.get("content") and not st.get("media_file_ids"):
            await query.answer("Add a message or media first.", show_alert=True)
            return
        st["step"] = "expiry"
        await _set_state(query.from_user.id, st)
        await query.message.edit_text(
            "🛠 <b>Step 4 — Expiry</b>\n\nChoose a lifetime for this whisper:",
            reply_markup=create_flow_kb("expiry"),
        )
        await query.answer()
        return

    if action == "exp":
        st = await _load_state(query.from_user.id)
        if not st:
            await query.answer("Session expired.", show_alert=True)
            return
        val = int(parts[2])
        st["expires_at"] = (now_ts() + val) if val > 0 else None
        st["step"] = "onetime"
        await _set_state(query.from_user.id, st)
        await query.message.edit_text(
            "🛠 <b>Step 5 — One-Time?</b>\n\n"
            "Should this whisper self-destruct after first open?",
            reply_markup=create_flow_kb("onetime"),
        )
        await query.answer()
        return

    if action == "ot":
        st = await _load_state(query.from_user.id)
        if not st:
            await query.answer("Session expired.", show_alert=True)
            return
        st["is_one_time"] = parts[2] == "1"
        st["step"] = "anonymous"
        await _set_state(query.from_user.id, st)
        await query.message.edit_text(
            "🛠 <b>Step 6 — Anonymous?</b>\n\n"
            "Hide your sender identity in the whisper card.\n"
            "<i>Note: Telegram cannot fully anonymise a bot-mediated message.</i>",
            reply_markup=create_flow_kb("anonymous"),
        )
        await query.answer()
        return

    if action == "anon":
        st = await _load_state(query.from_user.id)
        if not st:
            await query.answer("Session expired.", show_alert=True)
            return
        st["is_anonymous"] = parts[2] == "1"
        st["step"] = "confirm"
        await _set_state(query.from_user.id, st)
        await query.message.edit_text(
            _build_confirm_text(st),
            reply_markup=create_flow_kb("confirm"),
        )
        await query.answer()
        return

    if action == "go":
        st = await _load_state(query.from_user.id)
        if not st:
            await query.answer("Session expired.", show_alert=True)
            return
        # Build the whisper
        try:
            if st.get("media_file_ids"):
                doc = await whisper_service.create_media_whisper(
                    sender_id=query.from_user.id,
                    sender_first=query.from_user.first_name or "",
                    sender_last=query.from_user.last_name or "",
                    sender_username=query.from_user.username or "",
                    recipient_handles=st.get("recipient_handles", []),
                    recipient_ids=st.get("recipient_ids", []),
                    media_type=st["media_type"],
                    media_file_ids=st["media_file_ids"],
                    caption=st.get("caption", "") or st.get("content", ""),
                    expires_at=st.get("expires_at"),
                    is_one_time=st.get("is_one_time", False),
                    is_anonymous=st.get("is_anonymous", False),
                    chat_id=query.message.chat.id,
                )
            else:
                doc = await whisper_service.create_text_whisper(
                    sender_id=query.from_user.id,
                    sender_first=query.from_user.first_name or "",
                    sender_last=query.from_user.last_name or "",
                    sender_username=query.from_user.username or "",
                    recipient_handles=st.get("recipient_handles", []),
                    recipient_ids=st.get("recipient_ids", []),
                    content=st.get("content", ""),
                    expires_at=st.get("expires_at"),
                    is_one_time=st.get("is_one_time", False),
                    is_anonymous=st.get("is_anonymous", False),
                    chat_id=query.message.chat.id,
                )
        except Exception as e:  # noqa: BLE001
            log.exception("create failed: %s", e)
            await query.answer("Failed to create whisper.", show_alert=True)
            return

        await _clear_state(query.from_user.id)
        await query.message.edit_text(
            f"✅ <b>Whisper created!</b>\n\n"
            f"<b>ID:</b> <code>{doc['whisper_id']}</code>\n\n"
            f"Forward the whisper card below to any chat to deliver it.\n"
            f"<i>Recipients can also open it from your </i>"
            f"<b>/history</b><i> via the inline button.</i>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("📤 Send to chat",
                  switch_inline_query=doc['whisper_id'])]]
            ),
        )
        await query.answer("Created ✓")
        return


def _build_confirm_text(st: Dict[str, Any]) -> str:
    rec = ", ".join(f"@{h}" for h in st.get("recipient_handles", [])) or "—"
    media = st.get("media_type")
    exp = st.get("expires_at")
    exp_str = "No expiry" if not exp else fmt_time_short(exp)
    content_preview = truncate(st.get("content", "") or st.get("caption", ""), 200)
    return (
        "🛠 <b>Step 7 — Confirm</b>\n\n"
        f"<b>To:</b> {html.escape(rec)}\n"
        f"<b>Media:</b> {media.upper() if media else 'Text only'}\n"
        f"<b>One-time:</b> {st.get('is_one_time', False)}\n"
        f"<b>Anonymous:</b> {st.get('is_anonymous', False)}\n"
        f"<b>Expires:</b> {exp_str}\n\n"
        f"<b>Preview:</b>\n<i>{html.escape(content_preview or '(media only)')}</i>\n\n"
        f"<i>Press Confirm to create the whisper.</i>"
    )


# ── Plain-text / media input during /create ───────────────────────
async def _handle_create_input(message: Message) -> None:
    st = await _load_state(message.from_user.id)
    if not st:
        # Not in /create flow — show a hint
        return

    # Auto-expire stale state
    if now_ts() - st.get("updated_at", 0) > CREATE_TIMEOUT:
        await _clear_state(message.from_user.id)
        return

    step = st.get("step")

    if step == "recipient":
        text = (message.text or "").strip()
        if not text:
            await message.reply_text("Please send a username or ID.")
            return
        # accept @username or #id1234
        handles = []
        ids = []
        for tok in text.split():
            tok = tok.strip().lstrip("@")
            if tok.startswith("#id") and tok[3:].isdigit():
                ids.append(int(tok[3:]))
            elif tok and tok[0].isalpha() and all(c.isalnum() or c == "_" for c in tok):
                handles.append(tok.lower())
            else:
                await message.reply_text(
                    f"❌ Couldn't parse '{tok}'.\n"
                    "Use <code>@username</code> or <code>#id123456789</code>.",
                )
                return
        st["recipient_handles"] = handles
        st["recipient_ids"] = ids
        st["step"] = "message"
        await _set_state(message.from_user.id, st)
        await message.reply_text(
            f"✅ Recipient set: {', '.join(f'@{h}' for h in handles) or ', '.join(f'#{i}' for i in ids)}\n\n"
            "<b>Step 2 — Message</b>\nType your whisper text, or send media.",
            reply_markup=create_flow_kb("message"),
        )
        return

    if step == "message":
        mtype, file_ids, caption = extract_media(message)
        if mtype and file_ids:
            st["media_type"] = mtype
            st["media_file_ids"] = file_ids
            st["caption"] = caption
            st["step"] = "media"
            await _set_state(message.from_user.id, st)
            await message.reply_text(
                f"✅ Media attached: <b>{mtype.upper()}</b>\n"
                "Send more, or press <b>Done</b>.",
                reply_markup=create_flow_kb("media"),
            )
            return
        if message.text:
            st["content"] = message.text.strip()
            st["step"] = "expiry"
            await _set_state(message.from_user.id, st)
            await message.reply_text(
                "✅ Message saved.\n\n<b>Step 4 — Expiry</b>",
                reply_markup=create_flow_kb("expiry"),
            )
            return
        await message.reply_text("Please send text or a media item.")

    if step == "media":
        mtype, file_ids, caption = extract_media(message)
        if mtype and file_ids:
            # Replace existing media
            st["media_type"] = mtype
            st["media_file_ids"] = file_ids
            if caption:
                st["caption"] = caption
            await _set_state(message.from_user.id, st)
            await message.reply_text(
                f"✅ Media updated: <b>{mtype.upper()}</b>\n"
                "Press <b>Done</b> when ready.",
                reply_markup=create_flow_kb("media"),
            )
            return
        await message.reply_text("Send a media item, or press Done.")


# ── history text ──────────────────────────────────────────────────
async def _show_history(message: Message, page: int = 1, direction: str = "sent") -> None:
    res = await HistoryDB.list_paginated(message.from_user.id, page=page, per_page=5, direction=direction)
    items = res["items"]
    if not items:
        text = f"📜 <b>Whisper History</b>\n\n<i>No {direction} whispers yet.</i>"
        await message.reply_text(text, reply_markup=history_nav_kb(1, 1, direction),
                                 disable_web_page_preview=True)
        return

    lines = [f"📜 <b>Whisper History</b> ({direction}) — page {res['page']}/{res['pages']}", ""]
    kb_rows = []
    for idx, it in enumerate(items, start=1):
        rec = ", ".join(f"@{h}" for h in it.get("recipient_handles", [])) or "—"
        preview = it.get("preview", "")
        status = it.get("status", "—").capitalize()
        mtype = it.get("media_type")
        tag = f" [{mtype.upper()}]" if mtype else ""
        created = fmt_time_short(it.get("created_at"))
        lines.append(
            f"{idx}. <b>{html.escape(rec)}</b>{tag}\n"
            f'   "{html.escape(truncate(preview, 50))}"\n'
            f"   Status: {status} • Created: {created}"
        )
        kb_rows.append([
            InlineKeyboardButton(f"{idx}. View", callback_data=f"vw:{it['whisper_id']}"),
            InlineKeyboardButton("🗑", callback_data=f"del:{it['whisper_id']}"),
        ])
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

    await message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(kb_rows),
                             disable_web_page_preview=True)
