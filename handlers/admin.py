"""
WhisperX – admin-only commands.

  /stats       – global statistics
  /users       – paginated user list
  /broadcast   – send a message to every user
  /ban         – ban a user  (reply or /ban <id> [reason])
  /unban       – lift a ban
  /logs        – toggle metadata-only logging
  /maintenance – toggle maintenance mode (blocks new whispers)
  /settings    – show current admin settings
"""
from __future__ import annotations

import asyncio
import html
import logging
from typing import Optional

from pyrogram import filters
from pyrogram.types import Message

from config import config
from database.users import UsersDB
from database.whispers import WhispersDB
from database.mongo import db
from utils.helpers import now_ts, fmt_time_full, display_name

log = logging.getLogger(__name__)

# Simple in-memory maintenance flag (single-process only).
# For multi-worker deployments, swap this for a Mongo-backed flag.
_MAINTENANCE = False


def is_maintenance() -> bool:
    return _MAINTENANCE


def register(app) -> None:
    @app.on_message(filters.command("stats"))
    async def _stats(_, message: Message):
        if not config.is_admin(message.from_user.id):
            return
        total_users = await UsersDB.count_total()
        total_whispers = await WhispersDB.count_total()
        today_whispers = await WhispersDB.count_today()
        opened = await WhispersDB.count_by_status("opened")
        expired = await WhispersDB.count_by_status("expired")
        media = await WhispersDB.count_media()
        active_users = await UsersDB.count_active_since(now_ts() - 86400)
        text = (
            "📊 <b>Bot Statistics</b>\n\n"
            f"👤 <b>Users:</b> {total_users:,}\n"
            f"🟢 <b>Active (24h):</b> {active_users:,}\n"
            f"💌 <b>Whispers:</b> {total_whispers:,}\n"
            f"📅 <b>Today's whispers:</b> {today_whispers:,}\n"
            f"👀 <b>Opened:</b> {opened:,}\n"
            f"⏳ <b>Expired:</b> {expired:,}\n"
            f"📎 <b>Media whispers:</b> {media:,}\n"
        )
        await message.reply_text(text, disable_web_page_preview=True)

    @app.on_message(filters.command("users"))
    async def _users(_, message: Message):
        if not config.is_admin(message.from_user.id):
            return
        page = 1
        if len(message.command) > 1 and message.command[1].isdigit():
            page = int(message.command[1])
        per_page = 25
        skip = (page - 1) * per_page
        cursor = (
            db.users.find({}, {"_id": 0, "user_id": 1, "first_name": 1,  # type: ignore[union-attr]
                                "last_name": 1, "username": 1, "created_at": 1})
            .sort("created_at", -1)
            .skip(skip)
            .limit(per_page)
        )
        rows = []
        async for u in cursor:
            name = display_name(u.get("first_name", ""), u.get("last_name", ""), u.get("username", ""))
            uname = u.get("username") or "—"
            uid = u.get("user_id")
            created = fmt_time_full(u.get("created_at"))
            rows.append(f"• <b>{html.escape(name)}</b>  @{html.escape(uname)}  <code>{uid}</code>  <i>{created}</i>")
        if not rows:
            await message.reply_text("No users on this page.")
            return
        header = f"👥 <b>Users – page {page}</b>\n\n"
        await message.reply_text(header + "\n".join(rows), disable_web_page_preview=True)

    @app.on_message(filters.command("broadcast"))
    async def _broadcast(_, message: Message):
        if not config.is_admin(message.from_user.id):
            return
        if not message.reply_to_message:
            await message.reply_text("Reply to a message with /broadcast to send it to everyone.")
            return
        sent = 0
        failed = 0
        async for uid in UsersDB.all_ids():
            try:
                await message.reply_to_message.copy(chat_id=uid)
                sent += 1
                await asyncio.sleep(0.05)  # be gentle on Telegram
            except Exception as e:  # noqa: BLE001
                failed += 1
                log.info("broadcast skip %s: %s", uid, e)
        await message.reply_text(f"📣 Broadcast done.\nSent: {sent}\nFailed: {failed}")

    @app.on_message(filters.command("ban"))
    async def _ban(_, message: Message):
        if not config.is_admin(message.from_user.id):
            return
        target_id: Optional[int] = None
        reason = ""
        if message.reply_to_message and message.reply_to_message.from_user:
            target_id = message.reply_to_message.from_user.id
            reason = " ".join(message.command[1:]) or ""
        elif len(message.command) > 1 and message.command[1].isdigit():
            target_id = int(message.command[1])
            reason = " ".join(message.command[2:]) or ""
        if not target_id:
            await message.reply_text("Usage: /ban <user_id> [reason]  •  or reply to a user.")
            return
        if config.is_admin(target_id):
            await message.reply_text("❌ Cannot ban an admin.")
            return
        await UsersDB.ban(target_id, reason=reason)
        await message.reply_text(f"🚫 Banned <code>{target_id}</code>.\nReason: {reason or '—'}")

    @app.on_message(filters.command("unban"))
    async def _unban(_, message: Message):
        if not config.is_admin(message.from_user.id):
            return
        if len(message.command) < 2 or not message.command[1].isdigit():
            await message.reply_text("Usage: /unban <user_id>")
            return
        target_id = int(message.command[1])
        await UsersDB.unban(target_id)
        await message.reply_text(f"✅ Unbanned <code>{target_id}</code>.")

    @app.on_message(filters.command("logs"))
    async def _logs(_, message: Message):
        if not config.is_admin(message.from_user.id):
            return
        # Toggle metadata-only logging in-memory.
        # NOTE: config is a frozen dataclass; we mutate the underlying __dict__
        # so the running process picks up the change. Set METADATA_ONLY_LOGS
        # in .env for persistence across restarts.
        new_val = not config.metadata_only_logs
        object.__setattr__(config, "metadata_only_logs", new_val)
        await message.reply_text(
            f"📝 Metadata-only logs: <b>{new_val}</b>\n"
            "<i>Note: this toggle resets on restart. Set METADATA_ONLY_LOGS=true in .env for persistence.</i>"
        )

    @app.on_message(filters.command("maintenance"))
    async def _maintenance(_, message: Message):
        global _MAINTENANCE
        if not config.is_admin(message.from_user.id):
            return
        _MAINTENANCE = not _MAINTENANCE
        await message.reply_text(f"🛠 Maintenance mode: <b>{'ON' if _MAINTENANCE else 'OFF'}</b>")
