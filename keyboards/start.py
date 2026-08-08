"""WhisperX – start / main menu keyboards."""
from __future__ import annotations

from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)


def start_kb() -> InlineKeyboardMarkup:
    """
    The first keyboard the user sees on /start.

    `switch_inline_query_current_chat` opens Telegram's chat picker and
    auto-inserts the bot's @username into the chosen chat — that's the
    "✍️ Use Me" magic.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✍️ Use Me", switch_inline_query_current_chat=""),
                InlineKeyboardButton("📖 Help", callback_data="help"),
            ],
            [
                InlineKeyboardButton("📜 Whisper History", callback_data="hist:1:sent"),
            ],
            [
                InlineKeyboardButton("🌐 Language", callback_data="lang"),
                InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
            ],
            [
                InlineKeyboardButton("🔐 Privacy", callback_data="privacy"),
            ],
        ]
    )


def use_me_kb(bot_username: str) -> InlineKeyboardMarkup:
    """
    Inline-mode entry button used inside help / other screens.
    `switch_inline_query` opens Telegram's chat picker.
    """
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✍️ Use Me",
                    switch_inline_query=bot_username,
                )
            ]
        ]
    )


def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✍️ Use Me", switch_inline_query_current_chat=""),
                InlineKeyboardButton("📖 Help", callback_data="help"),
            ],
            [
                InlineKeyboardButton("📜 Whisper History", callback_data="hist:1:sent"),
                InlineKeyboardButton("🔐 Privacy", callback_data="privacy"),
            ],
            [
                InlineKeyboardButton("🌐 Language", callback_data="lang"),
                InlineKeyboardButton("⚙️ Settings", callback_data="settings"),
            ],
        ]
    )
