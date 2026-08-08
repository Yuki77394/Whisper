"""
WhisperX – whisper creation/orchestration service.

Bridges the parser, the database, and the logger.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any

from database.whispers import WhispersDB
from database.users import UsersDB
from database.history import HistoryDB
from utils.helpers import now_ts, truncate, display_name
from .logger import LogService

log = logging.getLogger(__name__)


class WhisperService:
    def __init__(self, log_service: LogService):
        self.log_service = log_service

    async def create_text_whisper(
        self,
        *,
        sender_id: int,
        sender_first: str,
        sender_last: str,
        sender_username: str,
        recipient_handles: List[str],
        recipient_ids: List[int],
        content: str,
        expires_at: Optional[int] = None,
        is_one_time: bool = False,
        is_anonymous: bool = False,
        chat_id: Optional[int] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        # Resolve usernames -> ids where possible
        resolved_ids: List[int] = list(recipient_ids)
        for handle in recipient_handles:
            user = await UsersDB.get_by_username(handle)
            if user and user.get("user_id") not in resolved_ids:
                resolved_ids.append(user["user_id"])

        sender_name = display_name(sender_first, sender_last, sender_username)

        doc = await WhispersDB.create(
            sender_id=sender_id,
            sender_name=sender_name,
            recipient_ids=resolved_ids,
            recipient_handles=recipient_handles,
            content=content,
            media_type=None,
            media_file_ids=None,
            caption=None,
            expires_at=expires_at,
            is_one_time=is_one_time,
            is_anonymous=is_anonymous,
            reply_to_message_id=reply_to_message_id,
            chat_id=chat_id,
        )

        # Sender's history entry
        await HistoryDB.add(
            user_id=sender_id,
            whisper_id=doc["whisper_id"],
            recipient_handles=recipient_handles,
            preview=truncate(content, 120),
            media_type=None,
            status="unopened",
            created_at=doc["created_at"],
            direction="sent",
        )

        # Recipient history entries (only those we could resolve)
        for rid in resolved_ids:
            await HistoryDB.add(
                user_id=rid,
                whisper_id=doc["whisper_id"],
                recipient_handles=[sender_username or sender_name],
                preview=truncate(content, 120),
                media_type=None,
                status="unopened",
                created_at=doc["created_at"],
                direction="received",
            )

        await self.log_service.log_create(whisper_doc=doc, content_preview=truncate(content, 200))
        return doc

    async def create_media_whisper(
        self,
        *,
        sender_id: int,
        sender_first: str,
        sender_last: str,
        sender_username: str,
        recipient_handles: List[str],
        recipient_ids: List[int],
        media_type: str,
        media_file_ids: List[str],
        caption: str = "",
        expires_at: Optional[int] = None,
        is_one_time: bool = False,
        is_anonymous: bool = False,
        chat_id: Optional[int] = None,
        reply_to_message_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        resolved_ids: List[int] = list(recipient_ids)
        for handle in recipient_handles:
            user = await UsersDB.get_by_username(handle)
            if user and user.get("user_id") not in resolved_ids:
                resolved_ids.append(user["user_id"])

        sender_name = display_name(sender_first, sender_last, sender_username)

        doc = await WhispersDB.create(
            sender_id=sender_id,
            sender_name=sender_name,
            recipient_ids=resolved_ids,
            recipient_handles=recipient_handles,
            content="",
            media_type=media_type,
            media_file_ids=media_file_ids,
            caption=caption,
            expires_at=expires_at,
            is_one_time=is_one_time,
            is_anonymous=is_anonymous,
            reply_to_message_id=reply_to_message_id,
            chat_id=chat_id,
        )

        await HistoryDB.add(
            user_id=sender_id,
            whisper_id=doc["whisper_id"],
            recipient_handles=recipient_handles,
            preview=truncate(caption, 120) or f"[{media_type.upper()}]",
            media_type=media_type,
            status="unopened",
            created_at=doc["created_at"],
            direction="sent",
        )

        for rid in resolved_ids:
            await HistoryDB.add(
                user_id=rid,
                whisper_id=doc["whisper_id"],
                recipient_handles=[sender_username or sender_name],
                preview=truncate(caption, 120) or f"[{media_type.upper()}]",
                media_type=media_type,
                status="unopened",
                created_at=doc["created_at"],
                direction="received",
            )

        await self.log_service.log_create(
            whisper_doc=doc,
            content_preview=truncate(caption, 200),
        )
        return doc
