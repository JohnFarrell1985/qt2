"""Tests for src/data/write_buffer.py"""
from __future__ import annotations

import asyncio

import pytest

from src.data.write_buffer import WriteBehindBuffer


# ====================================================================
# Helpers
# ====================================================================


class FakeModel:
    __tablename__ = "fake_table"


def _noop_flush(batch):
    pass


# ====================================================================
# put / flush cycle
# ====================================================================


class TestPutFlush:

    @pytest.mark.asyncio
    async def test_put_and_flush(self):
        flushed = []

        def _flush(batch):
            flushed.extend(batch)

        buf = WriteBehindBuffer(flush_fn=_flush, flush_interval=0.05, batch_size=10)
        await buf.start()

        await buf.put(FakeModel, [{"a": 1}])
        await buf.put(FakeModel, [{"a": 2}])

        await asyncio.sleep(0.15)
        await buf.stop()

        assert len(flushed) == 2
        assert buf.total_flushed == 2
        assert buf.total_errors == 0

    @pytest.mark.asyncio
    async def test_flush_groups_by_batch_size(self):
        flush_calls = []

        def _flush(batch):
            flush_calls.append(len(batch))

        buf = WriteBehindBuffer(flush_fn=_flush, flush_interval=0.05, batch_size=3)
        await buf.start()

        for i in range(5):
            await buf.put(FakeModel, [{"v": i}])

        await asyncio.sleep(0.2)
        await buf.stop()

        total = sum(flush_calls)
        assert total == 5

    @pytest.mark.asyncio
    async def test_get_stats(self):
        buf = WriteBehindBuffer(flush_fn=_noop_flush, flush_interval=0.05)
        await buf.start()

        await buf.put(FakeModel, [{"a": 1}])
        await asyncio.sleep(0.15)

        stats = buf.get_stats()
        assert stats["running"] is True
        assert stats["total_flushed"] == 1

        await buf.stop()
        stats = buf.get_stats()
        assert stats["running"] is False


# ====================================================================
# Graceful stop drains remaining
# ====================================================================


class TestGracefulStop:

    @pytest.mark.asyncio
    async def test_stop_drains_remaining(self):
        flushed = []

        def _flush(batch):
            flushed.extend(batch)

        buf = WriteBehindBuffer(
            flush_fn=_flush,
            flush_interval=10.0,
            batch_size=1000,
        )
        await buf.start()

        for i in range(5):
            await buf.put(FakeModel, [{"v": i}])

        await buf.stop()
        assert len(flushed) == 5

    @pytest.mark.asyncio
    async def test_stop_when_not_started(self):
        buf = WriteBehindBuffer(flush_fn=_noop_flush)
        await buf.stop()
        assert buf.total_flushed == 0


# ====================================================================
# Backpressure
# ====================================================================


class TestBackpressure:

    @pytest.mark.asyncio
    async def test_full_queue_blocks_put(self):
        buf = WriteBehindBuffer(
            flush_fn=_noop_flush,
            flush_interval=10.0,
            batch_size=1000,
            queue_maxsize=2,
        )

        await buf.put(FakeModel, [{"a": 1}])
        await buf.put(FakeModel, [{"a": 2}])
        assert buf.pending == 2

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                buf.put(FakeModel, [{"a": 3}]),
                timeout=0.1,
            )

        await buf.stop()


# ====================================================================
# Error handling
# ====================================================================


class TestErrorHandling:

    @pytest.mark.asyncio
    async def test_flush_error_counted(self):
        def _bad_flush(batch):
            raise RuntimeError("DB down")

        buf = WriteBehindBuffer(flush_fn=_bad_flush, flush_interval=0.05, batch_size=10)
        await buf.start()

        await buf.put(FakeModel, [{"a": 1}])
        await asyncio.sleep(3.0)
        await buf.stop()

        assert buf.total_errors >= 1
        assert buf.total_flushed == 0


# ====================================================================
# Context manager
# ====================================================================


class TestContextManager:

    @pytest.mark.asyncio
    async def test_async_context_manager(self):
        flushed = []

        def _flush(batch):
            flushed.extend(batch)

        async with WriteBehindBuffer(
            flush_fn=_flush,
            flush_interval=0.05,
            batch_size=10,
        ) as buf:
            await buf.put(FakeModel, [{"a": 1}])
            await asyncio.sleep(0.15)

        assert len(flushed) == 1

    @pytest.mark.asyncio
    async def test_double_start_is_noop(self):
        buf = WriteBehindBuffer(flush_fn=_noop_flush, flush_interval=0.05)
        await buf.start()
        first_task = buf._flush_task
        await buf.start()
        assert buf._flush_task is first_task
        await buf.stop()
