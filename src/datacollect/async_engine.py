"""异步采集引擎 — 双层 Semaphore + 三阶段管线"""
from __future__ import annotations

import asyncio
import time
from typing import Any, Callable

import pandas as pd

from src.common.logger import get_logger
from src.datacollect.async_rate_limiter import AsyncTokenBucketLimiter
from src.datacollect.base import CollectTask, CollectResult
from src.datacollect.circuit_breaker import CircuitBreaker
from src.datacollect.health import SourceHealthDashboard
from src.datacollect.validator import DataValidator

logger = get_logger(__name__)

_SENTINEL = object()


class AsyncCollectEngine:
    """双层 Semaphore 异步采集引擎。

    Architecture:
        - Global Semaphore: limits total concurrent tasks
        - Per-source Semaphore: limits concurrent tasks per data source
        - Per-domain rate limiter: controls request frequency
        - Pipeline stages: Fetch → Validate → Persist
    """

    def __init__(
        self,
        global_concurrency: int = 50,
        source_concurrency: dict[str, int] | None = None,
        source_rates: dict[str, tuple[float, int]] | None = None,
        validator: DataValidator | None = None,
        health_dashboard: SourceHealthDashboard | None = None,
    ):
        self._global_sem = asyncio.Semaphore(global_concurrency)
        self._source_sems: dict[str, asyncio.Semaphore] = {}
        if source_concurrency:
            for src, limit in source_concurrency.items():
                self._source_sems[src] = asyncio.Semaphore(limit)

        self._source_rates = source_rates or {}
        self._source_to_rate_domain: dict[str, str] = {}
        self._validator = validator or DataValidator()
        self._health = health_dashboard or SourceHealthDashboard.instance()

        self._fetch_queue: asyncio.Queue | None = None
        self._validate_queue: asyncio.Queue | None = None
        self._running = False

    @classmethod
    def from_registry(cls, registry: Any) -> AsyncCollectEngine:
        """Create engine from DataSourceRegistry, reading max_concurrent and rate config."""
        source_concurrency: dict[str, int] = {}
        source_rates: dict[str, tuple[float, int]] = {}
        for src_def in registry.list_all():
            source_concurrency[src_def.name] = src_def.max_concurrent
            domain = src_def.rate_domain
            existing = source_rates.get(domain)
            if existing is None or src_def.rate < existing[0]:
                source_rates[domain] = (src_def.rate, src_def.burst)
        engine = cls(
            source_concurrency=source_concurrency,
            source_rates=source_rates,
        )
        for src_def in registry.list_all():
            engine._source_to_rate_domain[src_def.name] = src_def.rate_domain
        return engine

    def _get_source_sem(self, source: str) -> asyncio.Semaphore:
        if source not in self._source_sems:
            self._source_sems[source] = asyncio.Semaphore(3)
        return self._source_sems[source]

    async def collect_one(
        self,
        task: CollectTask,
        collect_fn: Callable[[CollectTask], Any],
        is_sync: bool = True,
    ) -> CollectResult:
        """Execute a single collection task with dual-semaphore control.

        Args:
            task: The collection task
            collect_fn: The actual collection function to call
            is_sync: If True, wraps collect_fn with asyncio.to_thread
        """
        source_sem = self._get_source_sem(task.source)

        cb = CircuitBreaker.for_domain(task.source)
        if not cb.allow_request():
            raise RuntimeError(f"Circuit breaker OPEN for {task.source}")

        async with self._global_sem:
            async with source_sem:
                rate_domain = self._source_to_rate_domain.get(task.source, task.source)
                rate_info = self._source_rates.get(rate_domain)
                if rate_info:
                    limiter = await AsyncTokenBucketLimiter.for_domain(
                        rate_domain, rate_info[0], rate_info[1]
                    )
                    await limiter.acquire()

                start = time.monotonic()
                try:
                    if is_sync:
                        result = await asyncio.to_thread(collect_fn, task)
                    else:
                        result = await collect_fn(task)

                    elapsed = time.monotonic() - start
                    cb.record_success()
                    self._health.record_request(task.source, 200, elapsed)
                    return result

                except Exception:
                    elapsed = time.monotonic() - start
                    cb.record_failure()
                    self._health.record_request(task.source, 0, elapsed)
                    raise

    async def collect_batch(
        self,
        tasks: list[CollectTask],
        collect_fn: Callable[[CollectTask], Any],
        persist_fn: Callable[[list[CollectResult]], Any] | None = None,
        dead_letter_fn: Callable[[CollectTask, Exception], Any] | None = None,
        is_sync: bool = True,
    ) -> dict[str, int]:
        """Execute batch of tasks with concurrent collection, validation, persistence.

        Returns dict with counts: {total, success, failed, invalid}
        """
        stats = {"total": len(tasks), "success": 0, "failed": 0, "invalid": 0}
        results_batch: list[CollectResult] = []
        lock = asyncio.Lock()

        async def _do_one(task: CollectTask) -> None:
            try:
                result = await self.collect_one(task, collect_fn, is_sync)

                if self._validator and isinstance(getattr(result, "data", None), pd.DataFrame):
                    vr = self._validator.validate(result.data, task.data_type)
                    if not vr.is_valid:
                        async with lock:
                            stats["invalid"] += 1
                        logger.warning(
                            "validation failed for task %s: %d errors",
                            task.task_id,
                            len(vr.errors),
                        )
                        if dead_letter_fn:
                            await asyncio.to_thread(
                                dead_letter_fn,
                                task,
                                ValueError(f"Validation failed: {vr.errors[:3]}"),
                            )
                        return

                async with lock:
                    results_batch.append(result)
                    stats["success"] += 1

            except Exception as exc:
                async with lock:
                    stats["failed"] += 1
                logger.warning("task %s failed: %s", task.task_id, exc)
                if dead_letter_fn:
                    try:
                        await asyncio.to_thread(dead_letter_fn, task, exc)
                    except Exception:
                        logger.exception("dead_letter_fn failed for task %s", task.task_id)

        await asyncio.gather(*[_do_one(t) for t in tasks], return_exceptions=False)

        if persist_fn and results_batch:
            try:
                await asyncio.to_thread(persist_fn, results_batch)
            except Exception:
                logger.exception("persist_fn failed for %d results", len(results_batch))

        logger.info(
            "batch complete: total=%d success=%d failed=%d invalid=%d",
            stats["total"],
            stats["success"],
            stats["failed"],
            stats["invalid"],
        )
        return stats

    async def run_pipeline(
        self,
        tasks: list[CollectTask],
        collect_fn: Callable,
        persist_fn: Callable,
        dead_letter_fn: Callable | None = None,
        is_sync: bool = True,
        fetch_queue_size: int = 50,
        validate_queue_size: int = 100,
        persist_batch_size: int = 100,
    ) -> dict[str, int]:
        """Three-stage async pipeline with backpressure.

        Stages: Fetch → Validate → Persist
        Each stage connected by bounded asyncio.Queue.
        When downstream is slow, upstream automatically throttles.
        """
        self._fetch_queue = asyncio.Queue(maxsize=fetch_queue_size)
        self._validate_queue = asyncio.Queue(maxsize=validate_queue_size)
        self._running = True

        stats = {"total": len(tasks), "success": 0, "failed": 0, "invalid": 0}
        lock = asyncio.Lock()

        async def _fetch_stage() -> None:
            for task in tasks:
                try:
                    result = await self.collect_one(task, collect_fn, is_sync)
                    await self._fetch_queue.put((task, result))
                except Exception as exc:
                    async with lock:
                        stats["failed"] += 1
                    if dead_letter_fn:
                        try:
                            await asyncio.to_thread(dead_letter_fn, task, exc)
                        except Exception:
                            logger.exception("dead_letter_fn error for task %s", task.task_id)
            await self._fetch_queue.put(_SENTINEL)

        async def _validate_stage() -> None:
            while True:
                item = await self._fetch_queue.get()
                if item is _SENTINEL:
                    await self._validate_queue.put(_SENTINEL)
                    break
                task, result = item
                if self._validator and isinstance(getattr(result, "data", None), pd.DataFrame):
                    vr = self._validator.validate(result.data, task.data_type)
                    if not vr.is_valid:
                        async with lock:
                            stats["invalid"] += 1
                        continue
                await self._validate_queue.put(result)

        async def _persist_stage() -> None:
            batch: list[CollectResult] = []
            while True:
                item = await self._validate_queue.get()
                if item is _SENTINEL:
                    break
                batch.append(item)
                if len(batch) >= persist_batch_size:
                    try:
                        await asyncio.to_thread(persist_fn, batch)
                        async with lock:
                            stats["success"] += len(batch)
                    except Exception:
                        async with lock:
                            stats["failed"] += len(batch)
                        logger.exception("persist failed for %d results", len(batch))
                    batch = []
            if batch:
                try:
                    await asyncio.to_thread(persist_fn, batch)
                    async with lock:
                        stats["success"] += len(batch)
                except Exception:
                    async with lock:
                        stats["failed"] += len(batch)
                    logger.exception("persist failed for %d results", len(batch))

        await asyncio.gather(
            _fetch_stage(),
            _validate_stage(),
            _persist_stage(),
        )

        self._running = False
        logger.info("pipeline complete: %s", stats)
        return stats

    @property
    def running(self) -> bool:
        return self._running
