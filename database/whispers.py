"""WhisperX – whisper + access collection helpers."""
from __future__ import annotations

import secrets
import time
from typing import Optional, List, Dict, Any

from .mongo import db


def new_whisper_id() -> str:
    """24-char URL-safe hex id. Used in callback data."""
    return secrets.token_hex(12)


class WhispersDB:
    # ── create ──────────────────────────────────────────────────────
    @staticmethod
    async def create(
        *,
        sender_id: int,
        sender_name: str,
        recipient_ids: List[int],
        recipient_handles: List[str],
        content: str,
        media_type: Optional[str] = None,
        media_file_ids: Optional[List[str]] = None,
        caption: Optional[str] = None,
        expires_at: Optional[int] = None,
        is_one_time: bool = False,
        is_anonymous: bool = False,
        reply_to_message_id: Optional[int] = None,
        chat_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        wid = new_whisper_id()
        now = int(time.time())
        doc = {
            "whisper_id": wid,
            "sender_id": sender_id,
            "sender_name": sender_name,
            "recipient_ids": recipient_ids,
            "recipient_handles": recipient_handles,
            "content": content or "",
            "media_type": media_type,
            "media_file_ids": media_file_ids or [],
            "caption": caption or "",
            "created_at": now,
            "expires_at": expires_at,
            "is_one_time": bool(is_one_time),
            "is_anonymous": bool(is_anonymous),
            "status": "unopened",          # unopened | opened | expired | deleted
            "opened_by": [],
            "opened_at": [],
            "chat_id": chat_id,
            "reply_to_message_id": reply_to_message_id,
        }
        await db.whispers.insert_one(doc)  # type: ignore[union-attr]

        # Access records – one per recipient
        for rid in recipient_ids:
            await db.whisper_access.update_one(  # type: ignore[union-attr]
                {"whisper_id": wid, "user_id": rid},
                {
                    "$setOnInsert": {
                        "whisper_id": wid,
                        "user_id": rid,
                        "opened": False,
                        "opened_at": None,
                    }
                },
                upsert=True,
            )

        # Stats counter
        await WhispersDB._bump_stats(now)
        return doc

    @staticmethod
    async def _bump_stats(now: int) -> None:
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        await db.stats.update_one(  # type: ignore[union-attr]
            {"day": day},
            {"$inc": {"whispers_created": 1}, "$setOnInsert": {"day": day}},
            upsert=True,
        )

    # ── read ────────────────────────────────────────────────────────
    @staticmethod
    async def get(whisper_id: str) -> Optional[Dict[str, Any]]:
        return await db.whispers.find_one({"whisper_id": whisper_id})  # type: ignore[union-attr]

    @staticmethod
    async def can_open(whisper_id: str, user_id: int) -> bool:
        doc = await db.whisper_access.find_one(  # type: ignore[union-attr]
            {"whisper_id": whisper_id, "user_id": user_id}
        )
        return doc is not None

    @staticmethod
    async def is_opened_by(whisper_id: str, user_id: int) -> bool:
        doc = await db.whisper_access.find_one(  # type: ignore[union-attr]
            {"whisper_id": whisper_id, "user_id": user_id}
        )
        return bool(doc and doc.get("opened"))

    # ── update ──────────────────────────────────────────────────────
    @staticmethod
    async def mark_opened(whisper_id: str, user_id: int) -> bool:
        """
        Mark a whisper opened for a specific user.
        Returns True if first-time open (for one-time logic).
        """
        now = int(time.time())
        existing = await db.whisper_access.find_one(  # type: ignore[union-attr]
            {"whisper_id": whisper_id, "user_id": user_id}
        )
        if not existing:
            return False
        if existing.get("opened"):
            return False  # already opened by this user

        await db.whisper_access.update_one(  # type: ignore[union-attr]
            {"whisper_id": whisper_id, "user_id": user_id},
            {"$set": {"opened": True, "opened_at": now}},
        )
        await db.whispers.update_one(  # type: ignore[union-attr]
            {"whisper_id": whisper_id},
            {
                "$addToSet": {"opened_by": user_id, "opened_at": now},
                "$set": {"status": "opened"},
            },
        )
        return True

    @staticmethod
    async def delete(whisper_id: str) -> None:
        await db.whispers.update_one(  # type: ignore[union-attr]
            {"whisper_id": whisper_id},
            {"$set": {"status": "deleted", "content": "", "media_file_ids": [], "caption": ""}},
        )
        await db.whisper_access.delete_many({"whisper_id": whisper_id})  # type: ignore[union-attr]

    @staticmethod
    async def mark_expired(whisper_id: str) -> None:
        await db.whispers.update_one(  # type: ignore[union-attr]
            {"whisper_id": whisper_id},
            {"$set": {"status": "expired", "content": "", "media_file_ids": [], "caption": ""}},
        )

    @staticmethod
    async def list_expired(now_ts: int, limit: int = 100):
        cursor = db.whispers.find(  # type: ignore[union-attr]
            {
                "expires_at": {"$lte": now_ts, "$ne": None},
                "status": {"$in": ["unopened", "opened"]},
            },
            {"whisper_id": 1},
            limit=limit,
        )
        return [doc["whisper_id"] async for doc in cursor]

    # ── stats ───────────────────────────────────────────────────────
    @staticmethod
    async def count_total() -> int:
        return await db.whispers.count_documents({})  # type: ignore[union-attr]

    @staticmethod
    async def count_today() -> int:
        start = int(time.time()) - 86400
        return await db.whispers.count_documents({"created_at": {"$gte": start}})  # type: ignore[union-attr]

    @staticmethod
    async def count_by_status(status: str) -> int:
        return await db.whispers.count_documents({"status": status})  # type: ignore[union-attr]

    @staticmethod
    async def count_media() -> int:
        return await db.whispers.count_documents({"media_type": {"$ne": None}})  # type: ignore[union-attr]
