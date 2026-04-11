"""异步写缓冲层 — asyncio.Queue 解耦采集与持久化"""
from __future__ import annotations

import asyncio
from typing import Any, Callable

from src.common.logger import get_logger

logger = get_logger(__name__)


class WriteBehindBuffer:
    """Write-behind buffer that decouples data collection from DB persistence.

    Data goes into an asyncio.Queue and a background flush task
    periodically drains it to the DB in batches.
    """

    def __init__(
        self,
        flush_fn: Callable[[list[tuple[Any, list[dict]]]], Any],
        flush_interval: float = 1.0,
        batch_size: int = 5000,
        queue_maxsize: int = 200,
    ):
        self._flush_fn = flush_fn
        self._flush_interval = flush_interval
        self._batch_size = batch_size
        self._queue: asyncio.Queue[tuple[Any, list[dict]]] = asyncio.Queue(maxsize=queue_maxsize)
        self._flush_task: asyncio.Task | None = None
        self._running = False
        self._total_flushed = 0
        self._total_errors = 0

    async def put(self, model: Any, records: list[dict]) -> None:
        """Add records to the write buffer.
        Blocks if buffer is full (backpressure)."""
        await self._queue.put((model, records))

    async def start(self) -> None:
        """Start the background flush loop."""
        if self._running:
            return
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info(
            "WriteBehindBuffer started (interval=%.1fs, batch_size=%d)",
            self._flush_interval,
            self._batch_size,
        )

    async def stop(self) -> None:
        """Stop the buffer, flushing remaining items."""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        remaining = self._drain_all()
        if remaining:
            await self._do_flush(remaining)

        logger.info(
            "WriteBehindBuffer stopped (total_flushed=%d, errors=%d)",
            self._total_flushed,
            self._total_errors,
        )

    async def _flush_loop(self) -> None:
        while self._running:
            batch = await self._drain_batch()
            if batch:
                await self._do_flush(batch)

    async def _drain_batch(self) -> list[tuple[Any, list[dict]]]:
        batch: list[tuple[Any, list[dict]]] = []
        try:
            while len(batch) < self._batch_size:
                item = await asyncio.wait_for(self._queue.get(), timeout=self._flush_interval)
                batch.append(item)
        except asyncio.TimeoutError:
            pass
        return batch

    def _drain_all(self) -> list[tuple[Any, list[dict]]]:
        items: list[tuple[Any, list[dict]]] = []
        while not self._queue.empty():
            try:
                items.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        return items

    async def _do_flush(
        self, batch: list[tuple[Any, list[dict]]], _retry: int = 0
    ) -> None:
        _MAX_RETRIES = 2
        try:
            await asyncio.to_thread(self._flush_fn, batch)
            self._total_flushed += len(batch)
            logger.debug("flushed %d items (total: %d)", len(batch), self._total_flushed)
        except Exception:
            if _retry < _MAX_RETRIES:
                logger.warning(
                    "flush failed for %d items, retry %d/%d",
                    len(batch), _retry + 1, _MAX_RETRIES,
                )
                await asyncio.sleep(0.5 * (2 ** _retry))
                await self._do_flush(batch, _retry=_retry + 1)
            else:
                self._total_errors += len(batch)
                logger.exception(
                    "flush permanently failed for %d items after %d retries",
                    len(batch), _MAX_RETRIES,
                )

    @property
    def pending(self) -> int:
        return self._queue.qsize()

    @property
    def total_flushed(self) -> int:
        return self._total_flushed

    @property
    def total_errors(self) -> int:
        return self._total_errors

    def get_stats(self) -> dict:
        return {
            "running": self._running,
            "pending": self.pending,
            "total_flushed": self._total_flushed,
            "total_errors": self._total_errors,
        }

    async def __aenter__(self) -> WriteBehindBuffer:
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.stop()
