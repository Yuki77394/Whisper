"""WhisperX – per-user whisper history (projection collection)."""
from __future__ import annotations

import time
from typing import Optional, Dict, Any, AsyncIterator

from .mongo import db


class HistoryDB:
    """Per-user history; only visible inside the bot's private chat."""

    @staticmethod
    async def add(
        *,
        user_id: int,
        whisper_id: str,
        recipient_handles: list,
        preview: str,
        media_type: Optional[str],
        status: str,
        created_at: int,
        direction: str = "sent",   # sent | received
    ) -> None:
        await db.history.insert_one(  # type: ignore[union-attr]
            {
                "user_id": user_id,
                "whisper_id": whisper_id,
                "recipient_handles": recipient_handles,
                "preview": preview,
                "media_type": media_type,
                "status": status,
                "direction": direction,
                "created_at": created_at,
            }
        )

    @staticmethod
    async def update_status(whisper_id: str, status: str) -> None:
        await db.history.update_many(  # type: ignore[union-attr]
            {"whisper_id": whisper_id},
            {"$set": {"status": status}},
        )

    @staticmethod
    async def list_paginated(
        user_id: int, *, page: int = 1, per_page: int = 5, direction: Optional[str] = None
    ) -> Dict[str, Any]:
        q: Dict[str, Any] = {"user_id": user_id}
        if direction:
            q["direction"] = direction
        total = await db.history.count_documents(q)  # type: ignore[union-attr]
        skip = max(0, (page - 1) * per_page)
        cursor = (
            db.history.find(q, {"_id": 0})  # type: ignore[union-attr]
            .sort("created_at", -1)
            .skip(skip)
            .limit(per_page)
        )
        items = await cursor.to_list(length=per_page)
        return {
            "items": items,
            "total": total,
            "page": page,
            "pages": max(1, (total + per_page - 1) // per_page),
            "per_page": per_page,
        }

    @staticmethod
    async def delete_for_user(user_id: int, whisper_id: str) -> bool:
        res = await db.history.delete_one({"user_id": user_id, "whisper_id": whisper_id})  # type: ignore[union-attr]
        return res.deleted_count > 0
