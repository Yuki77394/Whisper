"""WhisperX – /start, callback navigation, onboarding."""
from __future__ import annotations

import html
import logging

from pyrogram import filters
from pyrogram.types import (
    CallbackQuery,
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)

from config import config
from database.users import UsersDB
from keyboards.start import start_kb, main_menu_kb
from keyboards.help import help_kb, help_back_kb
from keyboards.settings import (
    privacy_kb, language_kb, settings_kb,
)

log = logging.getLogger(__name__)

# Module-level bot reference (injected in register()).
bot = None


WELCOME_TEXT = (
    "👋 <b>Hello, {name}!</b>\n\n"
    "Welcome to <b>WhisperX</b> 🔒\n\n"
    "Send private whispers directly from Telegram's inline mode.\n\n"
    "<b>You can send:</b>\n"
    "• Text\n"
    "• Photos\n"
    "• Videos\n"
    "• Voice Notes\n"
    "• Audio\n"
    "• GIFs\n"
    "• Stickers\n"
    "• Documents\n"
    "• Media Albums\n\n"
    "Only the intended recipient can open a private whisper.\n\n"
    "<i>Choose an option below to get started.</i>"
)

HELP_TEXT = (
    "📖 <b>WhisperX Help</b>\n\n"
    "Whisper messages privately using inline mode.\n\n"
    "<b>How to use:</b>\n\n"
    "<code>@BotUsername @username Hello</code>\n\n"
    "<b>OR</b>\n\n"
    "<code>@BotUsername Hello @username</code>\n\n"
    "You can also <b>reply</b> to a user's message:\n\n"
    "<code>@BotUsername Hello</code>\n\n"
    "<b>Supported content:</b>\n"
    "✅ Text\n"
    "✅ Photos\n"
    "✅ Videos\n"
    "✅ Voice Notes\n"
    "✅ Audio\n"
    "✅ GIFs\n"
    "✅ Stickers\n"
    "✅ Documents\n"
    "✅ Albums\n\n"
    "<b>Commands:</b>\n"
    "/start – Welcome screen\n"
    "/help – This page\n"
    "/create – Advanced whisper builder\n"
    "/history – Your whisper history\n"
    "/privacy – Privacy settings\n"
    "/settings – Bot settings\n"
    "/language – Change language\n"
    "/cancel – Cancel current creation\n"
)

PRIVACY_TEXT = (
    "🔐 <b>Privacy Mode</b>\n\n"
    "<b>When enabled:</b>\n"
    "• Opening a whisper minimises extra metadata leaks\n"
    "• Sender info is hidden where the inline card already conveys enough\n"
    "• Stored personal data is reduced where technically possible\n\n"
    "<b>What WhisperX actually stores:</b>\n"
    "• Your Telegram user ID, name, username (so recipients can be resolved)\n"
    "• The whisper content + media <code>file_id</code> until expiry or deletion\n"
    "• Open / expire timestamps for audit\n\n"
    "<b>Honest Telegram limitations:</b>\n"
    "• Telegram bots cannot prevent screenshots or external photos\n"
    "• Protected content only disables forwarding inside Telegram\n"
    "• Anonymity cannot be technically guaranteed beyond what the API exposes\n"
)

SETTINGS_TEXT = (
    "⚙️ <b>Settings</b>\n\n"
    "Choose what you'd like to adjust."
)

LANGUAGE_TEXT = (
    "🌐 <b>Language</b>\n\n"
    "More languages will be added soon. Currently only English is available."
)


# ── Register all start/help/navigation handlers ────────────────────
def register(app) -> None:
    global bot
    bot = app

    @app.on_message(filters.command("start"))
    async def _start_cmd(_, message: Message):
        await _upsert_user(message)
        name = html.escape(message.from_user.first_name or "friend")
        await message.reply_text(
            WELCOME_TEXT.format(name=name),
            reply_markup=start_kb(),
            disable_web_page_preview=True,
        )

    @app.on_message(filters.command("help"))
    async def _help_cmd(_, message: Message):
        await _upsert_user(message)
        await message.reply_text(
            HELP_TEXT,
            reply_markup=help_kb(),
            disable_web_page_preview=True,
        )

    @app.on_callback_query(filters.regex(r"^(start|help|settings|privacy|lang|noop)$"))
    async def _nav_callback(_, query: CallbackQuery):
        await _upsert_user_callback(query)
        action = query.data
        if action == "start":
            await query.message.edit_text(
                WELCOME_TEXT.format(name=html.escape(query.from_user.first_name or "friend")),
                reply_markup=start_kb(),
                disable_web_page_preview=True,
            )
        elif action == "help":
            await query.message.edit_text(HELP_TEXT, reply_markup=help_kb(),
                                          disable_web_page_preview=True)
        elif action == "settings":
            await query.message.edit_text(SETTINGS_TEXT, reply_markup=settings_kb(),
                                          disable_web_page_preview=True)
        elif action == "privacy":
            cur = await UsersDB.get_privacy_mode(query.from_user.id)
            await query.message.edit_text(PRIVACY_TEXT, reply_markup=privacy_kb(cur),
                                          disable_web_page_preview=True)
        elif action == "lang":
            user = await UsersDB.get(query.from_user.id) or {}
            await query.message.edit_text(LANGUAGE_TEXT,
                                          reply_markup=language_kb(user.get("language", "en")),
                                          disable_web_page_preview=True)
        elif action == "noop":
            await query.answer("✓")
        await query.answer()

    @app.on_callback_query(filters.regex(r"^priv:(on|off)$"))
    async def _privacy_toggle(_, query: CallbackQuery):
        choice = query.data.split(":")[1]
        enabled = choice == "on"
        await UsersDB.set_privacy_mode(query.from_user.id, enabled)
        await query.message.edit_text(
            PRIVACY_TEXT,
            reply_markup=privacy_kb(enabled),
            disable_web_page_preview=True,
        )
        await query.answer("Privacy mode " + ("enabled ✓" if enabled else "disabled ✓"))

    @app.on_callback_query(filters.regex(r"^lang:([a-z]{2})$"))
    async def _lang_pick(_, query: CallbackQuery):
        code = query.data.split(":")[1]
        await UsersDB.set_language(query.from_user.id, code)
        await query.message.edit_text(
            LANGUAGE_TEXT,
            reply_markup=language_kb(code),
            disable_web_page_preview=True,
        )
        await query.answer(f"Language set to {code.upper()} ✓")


# ── helpers ────────────────────────────────────────────────────────
async def _upsert_user(message: Message) -> None:
    u = message.from_user
    if not u:
        return
    await UsersDB.upsert(
        user_id=u.id,
        first_name=u.first_name or "",
        last_name=u.last_name or "",
        username=u.username or "",
    )


async def _upsert_user_callback(query: CallbackQuery) -> None:
    u = query.from_user
    if not u:
        return
    await UsersDB.upsert(
        user_id=u.id,
        first_name=u.first_name or "",
        last_name=u.last_name or "",
        username=u.username or "",
    )
