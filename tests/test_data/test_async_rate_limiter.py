"""Tests for src/datacollect/async_rate_limiter.py"""
from __future__ import annotations

import asyncio
import time

import pytest

from src.datacollect.async_rate_limiter import AsyncTokenBucketLimiter


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture(autouse=True)
def _clean_domain_limiters():
    """每个测试前后重置类级别的域限流器缓存。"""
    AsyncTokenBucketLimiter.reset_all()
    yield
    AsyncTokenBucketLimiter.reset_all()


# ====================================================================
# __init__ validation
# ====================================================================

class TestInit:

    def test_valid_params(self):
        limiter = AsyncTokenBucketLimiter(rate=10.0, burst=5)
        assert limiter.rate == 10.0
        assert limiter.burst == 5

    def test_zero_rate_raises(self):
        with pytest.raises(ValueError, match="rate must be positive"):
            AsyncTokenBucketLimiter(rate=0.0, burst=5)

    def test_negative_rate_raises(self):
        with pytest.raises(ValueError, match="rate must be positive"):
            AsyncTokenBucketLimiter(rate=-1.0, burst=5)

    def test_zero_burst_raises(self):
        with pytest.raises(ValueError, match="burst must be positive"):
            AsyncTokenBucketLimiter(rate=1.0, burst=0)

    def test_negative_burst_raises(self):
        with pytest.raises(ValueError, match="burst must be positive"):
            AsyncTokenBucketLimiter(rate=1.0, burst=-1)

    def test_jitter_clamped_to_range(self):
        limiter = AsyncTokenBucketLimiter(rate=1.0, burst=1, jitter_pct=2.0)
        assert limiter._jitter_pct == 1.0

        limiter2 = AsyncTokenBucketLimiter(rate=1.0, burst=1, jitter_pct=-0.5)
        assert limiter2._jitter_pct == 0.0


# ====================================================================
# acquire — basic
# ====================================================================

class TestAcquire:

    @pytest.mark.asyncio
    async def test_first_acquire_succeeds_immediately(self):
        limiter = AsyncTokenBucketLimiter(rate=10.0, burst=5, jitter_pct=0.0)
        t0 = time.monotonic()
        result = await limiter.acquire()
        elapsed = time.monotonic() - t0
        assert result is True
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_burst_allows_multiple_immediate_acquires(self):
        limiter = AsyncTokenBucketLimiter(rate=10.0, burst=3, jitter_pct=0.0)
        results = []
        for _ in range(3):
            results.append(await limiter.acquire())
        assert all(results)

    @pytest.mark.asyncio
    async def test_exceeding_burst_causes_wait(self):
        limiter = AsyncTokenBucketLimiter(rate=100.0, burst=1, jitter_pct=0.0)
        await limiter.acquire()

        t0 = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.005

    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self):
        limiter = AsyncTokenBucketLimiter(rate=100.0, burst=2, jitter_pct=0.0)
        await limiter.acquire()
        await limiter.acquire()

        await asyncio.sleep(0.05)
        t0 = time.monotonic()
        result = await limiter.acquire()
        elapsed = time.monotonic() - t0
        assert result is True
        assert elapsed < 0.05


# ====================================================================
# acquire — rate limiting timing
# ====================================================================

class TestRateLimitingTiming:

    @pytest.mark.asyncio
    async def test_rate_limits_requests(self):
        """rate=10 tokens/s, burst=1 => 每次 acquire 间隔约 0.1s。"""
        limiter = AsyncTokenBucketLimiter(rate=10.0, burst=1, jitter_pct=0.0)
        await limiter.acquire()

        t0 = time.monotonic()
        for _ in range(3):
            await limiter.acquire()
        elapsed = time.monotonic() - t0
        assert elapsed >= 0.25


# ====================================================================
# try_acquire
# ====================================================================

class TestTryAcquire:

    @pytest.mark.asyncio
    async def test_try_acquire_success(self):
        limiter = AsyncTokenBucketLimiter(rate=10.0, burst=1, jitter_pct=0.0)
        result = await limiter.try_acquire()
        assert result is True

    @pytest.mark.asyncio
    async def test_try_acquire_fails_when_empty(self):
        limiter = AsyncTokenBucketLimiter(rate=0.1, burst=1, jitter_pct=0.0)
        await limiter.acquire()
        result = await limiter.try_acquire()
        assert result is False

    @pytest.mark.asyncio
    async def test_try_acquire_does_not_block(self):
        limiter = AsyncTokenBucketLimiter(rate=0.1, burst=1, jitter_pct=0.0)
        await limiter.acquire()

        t0 = time.monotonic()
        await limiter.try_acquire()
        elapsed = time.monotonic() - t0
        assert elapsed < 0.05


# ====================================================================
# timeout
# ====================================================================

class TestTimeout:

    @pytest.mark.asyncio
    async def test_acquire_timeout_returns_false(self):
        limiter = AsyncTokenBucketLimiter(rate=0.5, burst=1, jitter_pct=0.0)
        await limiter.acquire()

        t0 = time.monotonic()
        result = await limiter.acquire(timeout=0.1)
        elapsed = time.monotonic() - t0
        assert result is False
        assert elapsed < 0.3

    @pytest.mark.asyncio
    async def test_acquire_within_timeout_succeeds(self):
        limiter = AsyncTokenBucketLimiter(rate=50.0, burst=1, jitter_pct=0.0)
        await limiter.acquire()
        result = await limiter.acquire(timeout=1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_zero_timeout_fails_when_empty(self):
        limiter = AsyncTokenBucketLimiter(rate=0.1, burst=1, jitter_pct=0.0)
        await limiter.acquire()
        result = await limiter.acquire(timeout=0.0)
        assert result is False


# ====================================================================
# for_domain — singleton
# ====================================================================

class TestForDomain:

    @pytest.mark.asyncio
    async def test_same_domain_returns_same_instance(self):
        a = await AsyncTokenBucketLimiter.for_domain("test", rate=1.0, burst=1)
        b = await AsyncTokenBucketLimiter.for_domain("test", rate=99.0, burst=99)
        assert a is b
        assert a.rate == 1.0

    @pytest.mark.asyncio
    async def test_different_domains_return_different_instances(self):
        a = await AsyncTokenBucketLimiter.for_domain("domain_a", rate=1.0, burst=1)
        b = await AsyncTokenBucketLimiter.for_domain("domain_b", rate=2.0, burst=2)
        assert a is not b
        assert a.rate == 1.0
        assert b.rate == 2.0

    @pytest.mark.asyncio
    async def test_reset_all_clears_cache(self):
        a = await AsyncTokenBucketLimiter.for_domain("test", rate=1.0, burst=1)
        AsyncTokenBucketLimiter.reset_all()
        b = await AsyncTokenBucketLimiter.for_domain("test", rate=2.0, burst=2)
        assert a is not b
        assert b.rate == 2.0


# ====================================================================
# concurrent acquire
# ====================================================================

class TestConcurrency:

    @pytest.mark.asyncio
    async def test_concurrent_acquires_respect_limit(self):
        """burst=3, 并发 5 个 acquire, 前 3 个应立即完成, 后 2 个需等待。"""
        limiter = AsyncTokenBucketLimiter(rate=100.0, burst=3, jitter_pct=0.0)
        results = await asyncio.gather(
            *[limiter.acquire(timeout=0.5) for _ in range(5)]
        )
        assert all(results)

    @pytest.mark.asyncio
    async def test_concurrent_try_acquires(self):
        """burst=2, 并发 5 个 try_acquire, 最多 2 个成功。"""
        limiter = AsyncTokenBucketLimiter(rate=0.1, burst=2, jitter_pct=0.0)
        results = await asyncio.gather(
            *[limiter.try_acquire() for _ in range(5)]
        )
        assert sum(results) <= 2
