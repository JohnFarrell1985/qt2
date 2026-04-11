"""Tests for src/datacollect/async_engine.py"""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pandas as pd
import pytest

from src.datacollect.async_engine import AsyncCollectEngine
from src.datacollect.async_rate_limiter import AsyncTokenBucketLimiter
from src.datacollect.base import CollectResult, CollectTask
from src.datacollect.circuit_breaker import CircuitBreaker
from src.datacollect.health import SourceHealthDashboard
from src.datacollect.validator import DataValidator, ValidationResult


# ====================================================================
# Fixtures
# ====================================================================


@pytest.fixture(autouse=True)
def _reset_singletons():
    """Reset domain-level singletons between tests."""
    AsyncTokenBucketLimiter.reset_all()
    CircuitBreaker.reset_all()
    SourceHealthDashboard.reset_instance()
    yield
    AsyncTokenBucketLimiter.reset_all()
    CircuitBreaker.reset_all()
    SourceHealthDashboard.reset_instance()


@pytest.fixture
def engine():
    return AsyncCollectEngine(global_concurrency=10)


def _make_task(source: str = "test_src", data_type: str = "stock_daily") -> CollectTask:
    return CollectTask(source=source, data_type=data_type)


def _ok_collect_fn(task: CollectTask) -> CollectResult:
    return CollectResult(source=task.source, data={"rows": 10})


def _fail_collect_fn(task: CollectTask) -> CollectResult:
    raise RuntimeError("connection timeout")


# ====================================================================
# collect_one
# ====================================================================


class TestCollectOne:

    @pytest.mark.asyncio
    async def test_basic_success(self, engine):
        task = _make_task()
        result = await engine.collect_one(task, _ok_collect_fn, is_sync=True)
        assert result.source == "test_src"
        assert result.data == {"rows": 10}

    @pytest.mark.asyncio
    async def test_async_collect_fn(self, engine):
        async def _async_fn(task):
            return CollectResult(source=task.source, data="async_ok")

        task = _make_task()
        result = await engine.collect_one(task, _async_fn, is_sync=False)
        assert result.data == "async_ok"

    @pytest.mark.asyncio
    async def test_collect_fn_exception_propagates(self, engine):
        task = _make_task()
        with pytest.raises(RuntimeError, match="connection timeout"):
            await engine.collect_one(task, _fail_collect_fn, is_sync=True)

    @pytest.mark.asyncio
    async def test_circuit_breaker_open_raises(self, engine):
        cb = CircuitBreaker.for_domain("test_src", failure_threshold=1)
        cb.force_open()

        task = _make_task()
        with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
            await engine.collect_one(task, _ok_collect_fn, is_sync=True)

    @pytest.mark.asyncio
    async def test_health_recorded_on_success(self):
        dashboard = SourceHealthDashboard()
        engine = AsyncCollectEngine(health_dashboard=dashboard)

        task = _make_task()
        await engine.collect_one(task, _ok_collect_fn, is_sync=True)

        health = dashboard.get_health("test_src")
        assert health.total_requests == 1
        assert health.success_count == 1

    @pytest.mark.asyncio
    async def test_health_recorded_on_failure(self):
        dashboard = SourceHealthDashboard()
        engine = AsyncCollectEngine(health_dashboard=dashboard)

        task = _make_task()
        with pytest.raises(RuntimeError):
            await engine.collect_one(task, _fail_collect_fn, is_sync=True)

        health = dashboard.get_health("test_src")
        assert health.total_requests == 1
        assert health.timeout_count == 1

    @pytest.mark.asyncio
    async def test_source_semaphore_limits_concurrency(self):
        engine = AsyncCollectEngine(
            global_concurrency=50,
            source_concurrency={"test_src": 2},
        )

        active = 0
        max_active = 0
        lock = asyncio.Lock()

        async def _slow_fn(task):
            nonlocal active, max_active
            async with lock:
                active += 1
                if active > max_active:
                    max_active = active
            await asyncio.sleep(0.05)
            async with lock:
                active -= 1
            return CollectResult(source=task.source, data=None)

        tasks_list = [_make_task() for _ in range(6)]
        await asyncio.gather(
            *[engine.collect_one(t, _slow_fn, is_sync=False) for t in tasks_list]
        )

        assert max_active <= 2

    @pytest.mark.asyncio
    async def test_default_source_sem_created(self, engine):
        task = _make_task(source="new_unknown_source")
        result = await engine.collect_one(task, _ok_collect_fn, is_sync=True)
        assert result.source == "new_unknown_source"
        assert "new_unknown_source" in engine._source_sems


# ====================================================================
# collect_batch
# ====================================================================


class TestCollectBatch:

    @pytest.mark.asyncio
    async def test_all_succeed(self, engine):
        tasks = [_make_task() for _ in range(5)]
        stats = await engine.collect_batch(tasks, _ok_collect_fn)
        assert stats["total"] == 5
        assert stats["success"] == 5
        assert stats["failed"] == 0

    @pytest.mark.asyncio
    async def test_some_fail(self, engine):
        call_count = 0

        def _mixed_fn(task):
            nonlocal call_count
            call_count += 1
            if call_count % 2 == 0:
                raise ValueError("fail")
            return CollectResult(source=task.source, data=None)

        tasks = [_make_task() for _ in range(4)]
        stats = await engine.collect_batch(tasks, _mixed_fn)
        assert stats["total"] == 4
        assert stats["success"] + stats["failed"] == 4

    @pytest.mark.asyncio
    async def test_persist_fn_called(self, engine):
        persisted = []

        def _persist(results):
            persisted.extend(results)

        tasks = [_make_task() for _ in range(3)]
        await engine.collect_batch(tasks, _ok_collect_fn, persist_fn=_persist)
        assert len(persisted) == 3

    @pytest.mark.asyncio
    async def test_dead_letter_fn_on_failure(self, engine):
        dead = []

        def _dead_letter(task, exc):
            dead.append((task.task_id, str(exc)))

        tasks = [_make_task() for _ in range(2)]
        await engine.collect_batch(tasks, _fail_collect_fn, dead_letter_fn=_dead_letter)
        assert len(dead) == 2

    @pytest.mark.asyncio
    async def test_validation_failure_counted(self):
        mock_validator = MagicMock(spec=DataValidator)
        mock_validator.validate.return_value = ValidationResult(
            is_valid=False,
            errors=[MagicMock()],
        )

        engine = AsyncCollectEngine(validator=mock_validator)

        def _df_fn(task):
            return CollectResult(source=task.source, data=pd.DataFrame({"a": [1]}))

        tasks = [_make_task() for _ in range(2)]
        stats = await engine.collect_batch(tasks, _df_fn)
        assert stats["invalid"] == 2
        assert stats["success"] == 0

    @pytest.mark.asyncio
    async def test_empty_batch(self, engine):
        stats = await engine.collect_batch([], _ok_collect_fn)
        assert stats["total"] == 0


# ====================================================================
# run_pipeline
# ====================================================================


class TestRunPipeline:

    @pytest.mark.asyncio
    async def test_pipeline_basic(self, engine):
        persisted = []

        def _persist(batch):
            persisted.extend(batch)

        tasks = [_make_task() for _ in range(5)]
        stats = await engine.run_pipeline(
            tasks,
            collect_fn=_ok_collect_fn,
            persist_fn=_persist,
            persist_batch_size=100,
        )
        assert stats["total"] == 5
        assert stats["success"] == 5
        assert len(persisted) == 5

    @pytest.mark.asyncio
    async def test_pipeline_with_failures(self, engine):
        call_count = 0

        def _mixed_fn(task):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ValueError("fail")
            return CollectResult(source=task.source, data=None)

        dead = []

        def _dead_letter(task, exc):
            dead.append(task.task_id)

        tasks = [_make_task() for _ in range(5)]
        stats = await engine.run_pipeline(
            tasks,
            collect_fn=_mixed_fn,
            persist_fn=lambda batch: None,
            dead_letter_fn=_dead_letter,
            persist_batch_size=100,
        )
        assert stats["failed"] >= 2
        assert len(dead) == 2

    @pytest.mark.asyncio
    async def test_pipeline_batched_persist(self, engine):
        persist_calls = []

        def _persist(batch):
            persist_calls.append(len(batch))

        tasks = [_make_task() for _ in range(5)]
        await engine.run_pipeline(
            tasks,
            collect_fn=_ok_collect_fn,
            persist_fn=_persist,
            persist_batch_size=2,
        )
        assert sum(persist_calls) == 5
        assert all(c <= 2 for c in persist_calls[:-1])

    @pytest.mark.asyncio
    async def test_pipeline_sets_running_flag(self, engine):
        assert engine.running is False

        tasks = [_make_task()]
        await engine.run_pipeline(
            tasks,
            collect_fn=_ok_collect_fn,
            persist_fn=lambda batch: None,
        )
        assert engine.running is False


# ====================================================================
# from_registry
# ====================================================================


class TestFromRegistry:

    def test_from_registry_creates_engine(self):
        mock_registry = MagicMock()
        mock_src = MagicMock()
        mock_src.name = "akshare"
        mock_src.max_concurrent = 5
        mock_src.rate_domain = "akshare"
        mock_src.rate = 2.0
        mock_src.burst = 3
        mock_registry.list_all.return_value = [mock_src]

        engine = AsyncCollectEngine.from_registry(mock_registry)
        assert "akshare" in engine._source_sems
        assert "akshare" in engine._source_rates
        assert engine._source_rates["akshare"] == (2.0, 3)
