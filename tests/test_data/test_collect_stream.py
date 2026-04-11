"""Tests for BaseCollector.collect_stream() — A29"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

from src.datacollect.base import (
    BaseCollector,
    CollectResult,
    CollectTask,
    StreamResult,
)


# ====================================================================
# Concrete stub collector for testing
# ====================================================================

class _StubCollector(BaseCollector):
    """最小实现, 用于测试 collect_stream。"""

    def __init__(self, side_effects: list | None = None):
        super().__init__(limiter=None)
        self._side_effects = list(side_effects or [])
        self._call_idx = 0

    def collect(self, task: CollectTask) -> CollectResult:
        if self._side_effects:
            effect = self._side_effects[self._call_idx % len(self._side_effects)]
            self._call_idx += 1
            if isinstance(effect, Exception):
                raise effect
            return effect
        return CollectResult(source="stub", data=task.params, collected_at=datetime.now())

    def health_check(self) -> bool:
        return True


def _make_tasks(n: int) -> list[CollectTask]:
    return [
        CollectTask(source="stub", data_type="test", params={"i": i})
        for i in range(n)
    ]


# ====================================================================
# StreamResult dataclass
# ====================================================================

class TestStreamResult:

    def test_fields(self):
        sr = StreamResult(total=10, success=8, failed=2)
        assert sr.total == 10
        assert sr.success == 8
        assert sr.failed == 2


# ====================================================================
# collect_stream — 正常流
# ====================================================================

class TestCollectStreamHappyPath:

    def test_all_success(self):
        collector = _StubCollector()
        tasks = _make_tasks(5)
        result = collector.collect_stream(tasks)
        assert result == StreamResult(total=5, success=5, failed=0)

    def test_empty_tasks(self):
        collector = _StubCollector()
        result = collector.collect_stream([])
        assert result == StreamResult(total=0, success=0, failed=0)

    def test_persist_fn_called_per_batch(self):
        collector = _StubCollector()
        collector.STREAM_BATCH_SIZE = 3
        tasks = _make_tasks(7)
        persist_fn = MagicMock()

        result = collector.collect_stream(tasks, persist_fn=persist_fn)

        assert result.success == 7
        assert persist_fn.call_count == 3  # batches: 3, 3, 1
        batch_sizes = [len(call.args[0]) for call in persist_fn.call_args_list]
        assert batch_sizes == [3, 3, 1]

    def test_single_task(self):
        collector = _StubCollector()
        tasks = _make_tasks(1)
        result = collector.collect_stream(tasks)
        assert result == StreamResult(total=1, success=1, failed=0)


# ====================================================================
# collect_stream — 失败处理
# ====================================================================

class TestCollectStreamFailures:

    def test_partial_failure(self):
        effects = [
            CollectResult(source="stub", data="ok"),
            RuntimeError("boom"),
            CollectResult(source="stub", data="ok"),
        ]
        collector = _StubCollector(side_effects=effects)
        tasks = _make_tasks(3)
        result = collector.collect_stream(tasks)
        assert result == StreamResult(total=3, success=2, failed=1)

    def test_all_fail(self):
        effects = [ValueError("fail")]
        collector = _StubCollector(side_effects=effects)
        tasks = _make_tasks(3)
        result = collector.collect_stream(tasks)
        assert result == StreamResult(total=3, success=0, failed=3)

    def test_dead_letter_fn_called(self):
        effects = [RuntimeError("err")]
        collector = _StubCollector(side_effects=effects)
        tasks = _make_tasks(2)
        dead_letter_fn = MagicMock()

        collector.collect_stream(tasks, dead_letter_fn=dead_letter_fn)

        assert dead_letter_fn.call_count == 2
        for call in dead_letter_fn.call_args_list:
            task_arg, exc_arg = call.args
            assert isinstance(task_arg, CollectTask)
            assert isinstance(exc_arg, RuntimeError)

    def test_persist_not_called_on_all_fail_batch(self):
        effects = [ValueError("fail")]
        collector = _StubCollector(side_effects=effects)
        collector.STREAM_BATCH_SIZE = 2
        tasks = _make_tasks(2)
        persist_fn = MagicMock()

        collector.collect_stream(tasks, persist_fn=persist_fn)

        persist_fn.assert_not_called()


# ====================================================================
# collect_stream — 批大小边界
# ====================================================================

class TestCollectStreamBatchBoundary:

    def test_exact_batch_boundary(self):
        collector = _StubCollector()
        collector.STREAM_BATCH_SIZE = 5
        tasks = _make_tasks(10)
        persist_fn = MagicMock()

        result = collector.collect_stream(tasks, persist_fn=persist_fn)

        assert result.success == 10
        assert persist_fn.call_count == 2

    def test_custom_batch_size(self):
        collector = _StubCollector()
        collector.STREAM_BATCH_SIZE = 2
        tasks = _make_tasks(5)
        persist_fn = MagicMock()

        result = collector.collect_stream(tasks, persist_fn=persist_fn)

        assert result.success == 5
        assert persist_fn.call_count == 3  # batches: 2, 2, 1

    def test_default_batch_size(self):
        assert BaseCollector.STREAM_BATCH_SIZE == 100
