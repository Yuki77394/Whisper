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
    async def can_open(whisper_id: str, user_id: int, username: str = "") -> bool:
        """Check whether a user is authorised to open a whisper.

        Authorization rules (in order):
          1. Public whisper (no recipient_ids AND no recipient_handles)
             → anyone can open.
          2. user_id is in recipient_ids → authorised.
          3. user_id has a whisper_access record → authorised.
          4. username (lowercased) is in recipient_handles → authorised
             (retroactive: the user_id is linked so future opens are fast).
        """
        doc = await db.whispers.find_one({"whisper_id": whisper_id})  # type: ignore[union-attr]
        if not doc:
            return False

        recipient_ids: list = doc.get("recipient_ids") or []
        recipient_handles: list = doc.get("recipient_handles") or []

        # 1. Public whisper — anyone can open
        if not recipient_ids and not recipient_handles:
            return True

        # 2. user_id is in recipient_ids
        if user_id in recipient_ids:
            return True

        # 3. whisper_access record exists
        access = await db.whisper_access.find_one(  # type: ignore[union-attr]
            {"whisper_id": whisper_id, "user_id": user_id}
        )
        if access:
            return True

        # 4. Username match — retroactive linking
        if username:
            uname = username.lstrip("@").lower()
            if uname in [h.lstrip("@").lower() for h in recipient_handles]:
                # Link this user_id to the whisper so future opens are fast
                await WhispersDB._link_recipient(whisper_id, user_id, doc)
                return True

        return False

    @staticmethod
    async def _link_recipient(whisper_id: str, user_id: int, doc: Optional[dict] = None) -> None:
        """Retroactively link a user_id to a whisper (username-based auth).

        Called when a user opens a whisper by username match but their
        user_id wasn't known at creation time. Adds the user_id to
        recipient_ids and creates a whisper_access record.
        """
        if doc is None:
            doc = await db.whispers.find_one({"whisper_id": whisper_id})  # type: ignore[union-attr]
        if not doc:
            return

        recipient_ids: list = doc.get("recipient_ids") or []
        if user_id not in recipient_ids:
            await db.whispers.update_one(  # type: ignore[union-attr]
                {"whisper_id": whisper_id},
                {"$addToSet": {"recipient_ids": user_id}},
            )

        await db.whisper_access.update_one(  # type: ignore[union-attr]
            {"whisper_id": whisper_id, "user_id": user_id},
            {
                "$setOnInsert": {
                    "whisper_id": whisper_id,
                    "user_id": user_id,
                    "opened": False,
                    "opened_at": None,
                }
            },
            upsert=True,
        )

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

        If no whisper_access record exists yet (e.g. public whisper, or
        username-matched recipient not yet linked), one is created so
        that the opened state is properly tracked.
        """
        now = int(time.time())
        existing = await db.whisper_access.find_one(  # type: ignore[union-attr]
            {"whisper_id": whisper_id, "user_id": user_id}
        )
        if existing and existing.get("opened"):
            return False  # already opened by this user

        # Upsert the access record (creates it if missing, e.g. public whisper)
        await db.whisper_access.update_one(  # type: ignore[union-attr]
            {"whisper_id": whisper_id, "user_id": user_id},
            {"$set": {"opened": True, "opened_at": now}},
            upsert=True,
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
