"""WhisperX – user collection helpers."""
from __future__ import annotations

import time
from typing import Optional, Dict, Any

from .mongo import db


class UsersDB:
    """Thin async wrapper around the `users` collection."""

    @staticmethod
    async def upsert(
        user_id: int,
        *,
        first_name: str = "",
        last_name: str = "",
        username: str = "",
        language: str = "en",
    ) -> None:
        """Insert or refresh a user record."""
        update: Dict[str, Any] = {
            "first_name": first_name,
            "last_name": last_name,
            "username": username.lstrip("@") if username else "",
            "username_lower": (username or "").lstrip("@").lower(),
            "last_seen": int(time.time()),
        }
        await db.users.update_one(  # type: ignore[union-attr]
            {"user_id": user_id},
            {
                "$set": update,
                "$setOnInsert": {
                    "user_id": user_id,
                    "created_at": int(time.time()),
                    "language": language,
                    "privacy_mode": False,
                    "is_banned": False,
                },
            },
            upsert=True,
        )

    @staticmethod
    async def get(user_id: int) -> Optional[Dict[str, Any]]:
        return await db.users.find_one({"user_id": user_id})  # type: ignore[union-attr]

    @staticmethod
    async def get_by_username(username: str) -> Optional[Dict[str, Any]]:
        uname = (username or "").lstrip("@").lower()
        if not uname:
            return None
        return await db.users.find_one({"username_lower": uname})  # type: ignore[union-attr]

    @staticmethod
    async def set_language(user_id: int, language: str) -> None:
        await db.users.update_one(  # type: ignore[union-attr]
            {"user_id": user_id}, {"$set": {"language": language}}
        )

    @staticmethod
    async def set_privacy_mode(user_id: int, enabled: bool) -> None:
        await db.users.update_one(  # type: ignore[union-attr]
            {"user_id": user_id}, {"$set": {"privacy_mode": bool(enabled)}}
        )

    @staticmethod
    async def get_privacy_mode(user_id: int) -> bool:
        doc = await db.users.find_one(  # type: ignore[union-attr]
            {"user_id": user_id}, {"privacy_mode": 1}
        )
        return bool(doc and doc.get("privacy_mode"))

    @staticmethod
    async def count_total() -> int:
        return await db.users.count_documents({})  # type: ignore[union-attr]

    @staticmethod
    async def count_active_since(ts: int) -> int:
        return await db.users.count_documents({"last_seen": {"$gte": ts}})  # type: ignore[union-attr]

    @staticmethod
    async def ban(user_id: int, reason: str = "") -> None:
        await db.bans.update_one(  # type: ignore[union-attr]
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "reason": reason, "banned_at": int(time.time())}},
            upsert=True,
        )
        await db.users.update_one(  # type: ignore[union-attr]
            {"user_id": user_id}, {"$set": {"is_banned": True}}
        )

    @staticmethod
    async def unban(user_id: int) -> None:
        await db.bans.delete_one({"user_id": user_id})  # type: ignore[union-attr]
        await db.users.update_one(  # type: ignore[union-attr]
            {"user_id": user_id}, {"$set": {"is_banned": False}}
        )

    @staticmethod
    async def is_banned(user_id: int) -> bool:
        doc = await db.bans.find_one({"user_id": user_id})  # type: ignore[union-attr]
        return doc is not None

    @staticmethod
    async def all_ids():
        async for doc in db.users.find({}, {"user_id": 1}):  # type: ignore[union-attr]
            yield doc["user_id"]
