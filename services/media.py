"""
WhisperX – media helpers.

Telegram `file_id`s are stable enough to store and re-send (they may rotate
every ~1 week for bots, but in practice re-sending usually works for the
lifespan of a whisper). We never store the raw bytes.

NOTE on the file_id rotation: if re-send fails with FILE_ID_INVALID, the bot
falls back to the text-only whisper card.
"""
from __future__ import annotations

import logging
from typing import Optional, List

from pyrogram.types import Message
from pyrogram.errors import FileIdInvalid, FileReferenceEmpty

log = logging.getLogger(__name__)


def detect_media_type(message: Message) -> Optional[str]:
    """Map a pyrogram Message to one of our media type strings."""
    if message.photo:
        return "photo"
    if message.video:
        return "video"
    if message.animation:
        return "gif"
    if message.voice:
        return "voice"
    if message.audio:
        return "audio"
    if message.document:
        return "document"
    if message.sticker:
        return "sticker"
    if message.video_note:
        return "video_note"
    return None


def extract_media(message: Message) -> tuple:
    """
    Returns (media_type, [file_id, ...], caption) tuple.

    For a single message the list contains exactly one file_id.
    Albums are handled at the handler level (grouped by media_group_id).
    """
    mtype = detect_media_type(message)
    if not mtype:
        return None, [], message.caption or ""

    obj = getattr(message, mtype if mtype != "gif" else "animation")
    file_id = getattr(obj, "file_id", None)
    caption = message.caption or ""

    if mtype == "photo":
        # photo has multiple sizes; pick the largest available
        sizes = sorted(message.photo.sizes, key=lambda s: s.file_size or 0, reverse=True) \
            if message.photo.sizes else []
        if sizes:
            file_id = sizes[0].file_id
    return mtype, [file_id] if file_id else [], caption


async def send_media_to_user(client, chat_id: int, media_type: str, file_ids: List[str], caption: str = "") -> bool:
    """
    Send a stored media whisper to the recipient. Returns True on success.

    If the first file_id is invalid, tries the remaining ones, then gives up.
    """
    if not file_ids:
        return False

    cap = caption or None
    last_err = None
    for fid in file_ids:
        try:
            if media_type == "photo":
                await client.send_photo(chat_id=chat_id, photo=fid, caption=cap)
            elif media_type == "video":
                await client.send_video(chat_id=chat_id, video=fid, caption=cap)
            elif media_type == "gif":
                await client.send_animation(chat_id=chat_id, animation=fid, caption=cap)
            elif media_type == "voice":
                await client.send_voice(chat_id=chat_id, voice=fid, caption=cap)
            elif media_type == "audio":
                await client.send_audio(chat_id=chat_id, audio=fid, caption=cap)
            elif media_type == "document":
                await client.send_document(chat_id=chat_id, document=fid, caption=cap)
            elif media_type == "sticker":
                await client.send_sticker(chat_id=chat_id, sticker=fid)
            elif media_type == "video_note":
                await client.send_video_note(chat_id=chat_id, video_note=fid)
            else:
                log.warning("Unknown media_type '%s' for file_id=%s", media_type, fid)
                continue
            return True
        except (FileIdInvalid, FileReferenceEmpty) as e:
            last_err = e
            log.warning("media send failed (file_id invalid): %s", e)
            continue
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.exception("media send failed: %s", e)
            continue

    if last_err:
        log.error("All file_ids failed for media whisper: %s", last_err)
    return False
