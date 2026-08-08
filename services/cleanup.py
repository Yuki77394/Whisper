"""
WhisperX – background cleanup worker.

Periodically scans for expired whispers, marks them expired, and
clears their content from the database (so stale data isn't kept).
"""
from __future__ import annotations

import asyncio
import logging

from config import config
from database.whispers import WhispersDB
from database.history import HistoryDB
from services.logger import LogService
from utils.helpers import now_ts

log = logging.getLogger(__name__)


class CleanupWorker:
    def __init__(self, log_service: LogService):
        self.log_service = log_service
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="cleanup-worker")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=10)
            except asyncio.TimeoutError:
                self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        interval = max(60, config.cleanup_interval_seconds)
        log.info("Cleanup worker started (interval=%ss)", interval)
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception as e:  # noqa: BLE001
                log.exception("cleanup tick failed: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue
        log.info("Cleanup worker stopped.")

    async def _tick(self) -> None:
        now = now_ts()
        expired_ids = await WhispersDB.list_expired(now, limit=100)
        if not expired_ids:
            return
        for wid in expired_ids:
            await WhispersDB.mark_expired(wid)
            await HistoryDB.update_status(wid, "expired")
            await self.log_service.log_expired(whisper_id=wid)
        log.info("Marked %d whispers expired", len(expired_ids))
