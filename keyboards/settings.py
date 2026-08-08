"""WhisperX – settings, privacy, language, history, /create keyboards."""
from __future__ import annotations

from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton


# ── Privacy ───────────────────────────────────────────────────────
def privacy_kb(current: bool) -> InlineKeyboardMarkup:
    enabled_label = "🔒 Enabled ✓" if current else "🔒 Enable"
    disabled_label = "❌ Disabled ✓" if not current else "❌ Disable"
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(enabled_label, callback_data="priv:on"),
                InlineKeyboardButton(disabled_label, callback_data="priv:off"),
            ],
            [InlineKeyboardButton("◀️ Back", callback_data="settings")],
        ]
    )


# ── Language ──────────────────────────────────────────────────────
def language_kb(current: str = "en") -> InlineKeyboardMarkup:
    langs = [("English", "en")]
    rows = []
    for label, code in langs:
        marker = " ✓" if code == current else ""
        rows.append([InlineKeyboardButton(label + marker, callback_data=f"lang:{code}")])
    rows.append([InlineKeyboardButton("◀️ Back", callback_data="start")])
    return InlineKeyboardMarkup(rows)


# ── Settings ──────────────────────────────────────────────────────
def settings_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔐 Privacy", callback_data="privacy"),
                InlineKeyboardButton("🌐 Language", callback_data="lang"),
            ],
            [
                InlineKeyboardButton("📜 History", callback_data="hist:1:sent"),
                InlineKeyboardButton("✍️ /create", callback_data="create:start"),
            ],
            [InlineKeyboardButton("◀️ Back", callback_data="start")],
        ]
    )


# ── History navigation ────────────────────────────────────────────
def history_nav_kb(page: int, pages: int, direction: str) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(f"📤 Sent" if direction == "sent" else "📤 Sent",
                                 callback_data=f"hist:1:sent"),
            InlineKeyboardButton(f"📥 Received" if direction == "received" else "📥 Received",
                                 callback_data=f"hist:1:received"),
        ]
    ]
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"hist:{page-1}:{direction}"))
    nav.append(InlineKeyboardButton(f"{page}/{pages}", callback_data="noop"))
    if page < pages:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"hist:{page+1}:{direction}"))
    rows.append(nav)
    rows.append([InlineKeyboardButton("◀️ Back", callback_data="start")])
    return InlineKeyboardMarkup(rows)


def history_item_kb(whisper_id: str, can_delete: bool, can_view: bool) -> InlineKeyboardMarkup:
    buttons = []
    if can_view:
        buttons.append(InlineKeyboardButton("👀 View", callback_data=f"vw:{whisper_id}"))
    if can_delete:
        buttons.append(InlineKeyboardButton("🗑 Delete", callback_data=f"del:{whisper_id}"))
    if not buttons:
        return InlineKeyboardMarkup([[InlineKeyboardButton("◀️ Back", callback_data="hist:1:sent")]])
    return InlineKeyboardMarkup([buttons, [InlineKeyboardButton("◀️ Back", callback_data="hist:1:sent")]])


# ── /create flow ──────────────────────────────────────────────────
def create_flow_kb(step: str) -> InlineKeyboardMarkup:
    if step == "start":
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✍️ Start New Whisper", callback_data="create:recipient")],
                [InlineKeyboardButton("❌ Cancel", callback_data="create:cancel")],
            ]
        )
    if step == "recipient":
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("➡️ Continue", callback_data="create:message")],
                [InlineKeyboardButton("❌ Cancel", callback_data="create:cancel")],
            ]
        )
    if step == "message":
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("⏭ Skip media", callback_data="create:media"),
                 InlineKeyboardButton("⏭ Skip text", callback_data="create:expiry")],
                [InlineKeyboardButton("❌ Cancel", callback_data="create:cancel")],
            ]
        )
    if step == "media":
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ Done, choose expiry", callback_data="create:expiry")],
                [InlineKeyboardButton("❌ Cancel", callback_data="create:cancel")],
            ]
        )
    if step == "expiry":
        opts = [
            ("No expiry", "0"),
            ("5 min", "300"),
            ("10 min", "600"),
            ("30 min", "1800"),
            ("1 hour", "3600"),
            ("24 hours", "86400"),
            ("7 days", "604800"),
        ]
        rows = []
        row = []
        for label, val in opts:
            row.append(InlineKeyboardButton(label, callback_data=f"create:exp:{val}"))
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        rows.append([InlineKeyboardButton("❌ Cancel", callback_data="create:cancel")])
        return InlineKeyboardMarkup(rows)
    if step == "onetime":
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔥 One-time", callback_data="create:ot:1"),
                 InlineKeyboardButton("♾️ Multiple opens", callback_data="create:ot:0")],
                [InlineKeyboardButton("❌ Cancel", callback_data="create:cancel")],
            ]
        )
    if step == "anonymous":
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("👤 Anonymous", callback_data="create:anon:1"),
                 InlineKeyboardButton("📛 Show sender", callback_data="create:anon:0")],
                [InlineKeyboardButton("❌ Cancel", callback_data="create:cancel")],
            ]
        )
    if step == "confirm":
        return InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("✅ Confirm & Create", callback_data="create:go")],
                [InlineKeyboardButton("❌ Cancel", callback_data="create:cancel")],
            ]
        )
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="create:cancel")]])


# ── Expiry (used outside /create too) ─────────────────────────────
def expiry_kb(prefix: str = "exp") -> InlineKeyboardMarkup:
    opts = [("5m", "300"), ("10m", "600"), ("30m", "1800"),
            ("1h", "3600"), ("24h", "86400"), ("7d", "604800")]
    rows = []
    row = []
    for label, val in opts:
        row.append(InlineKeyboardButton(label, callback_data=f"{prefix}:{val}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("♾️ No expiry", callback_data=f"{prefix}:0")])
    return InlineKeyboardMarkup(rows)


# ── Whisper delivery card ─────────────────────────────────────────
def whisper_open_kb(whisper_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("👀 Open Whisper", callback_data=f"op:{whisper_id}")]]
    )


def close_only_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("✖️ Close", callback_data="noop")]]
    )
