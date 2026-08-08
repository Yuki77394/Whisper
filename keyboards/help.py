"""WhisperX – help & navigation keyboards."""
from __future__ import annotations

from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from config import config


def help_kb() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("📜 History", callback_data="hist:1:sent"),
            InlineKeyboardButton("🔐 Privacy", callback_data="privacy"),
        ],
        [
            InlineKeyboardButton("✍️ Try Inline", switch_inline_query=config.app_name.lower()),
            InlineKeyboardButton("💬 Support", url=config.support_chat or "https://t.me/"),
        ],
        [
            InlineKeyboardButton("🌐 Language", callback_data="lang"),
            InlineKeyboardButton("📢 Updates", url=config.update_channel or "https://t.me/"),
        ],
        [InlineKeyboardButton("◀️ Back", callback_data="start")],
    ]
    return InlineKeyboardMarkup(rows)


def help_back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("◀️ Back", callback_data="help")]]
    )
