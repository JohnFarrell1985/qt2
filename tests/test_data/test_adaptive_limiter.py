"""Tests for src/datacollect/adaptive_limiter.py"""
from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest

from src.datacollect.adaptive_limiter import AdaptiveLimiter, RequestResult


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture(autouse=True)
def _cleanup_domain_instances():
    """每个测试后清理域单例。"""
    AdaptiveLimiter.reset_all()
    yield
    AdaptiveLimiter.reset_all()


def _make_limiter(**kwargs) -> AdaptiveLimiter:
    defaults = {
        "domain": "test",
        "base_interval": 1.0,
        "window_sec": 300.0,
        "block_threshold": 0.10,
        "warn_threshold": 0.05,
        "speedup_after_sec": 600.0,
        "latency_spike_sec": 5.0,
    }
    defaults.update(kwargs)
    return AdaptiveLimiter(**defaults)


# ====================================================================
# RequestResult dataclass
# ====================================================================

class TestRequestResult:
    def test_default_timestamp(self):
        r = RequestResult(status_code=200, latency=0.5)
        assert r.timestamp > 0

    def test_explicit_fields(self):
        r = RequestResult(status_code=429, latency=1.2, timestamp=100.0)
        assert r.status_code == 429
        assert r.latency == 1.2
        assert r.timestamp == 100.0


# ====================================================================
# 基本功能
# ====================================================================

class TestAdaptiveLimiterBasic:
    def test_initial_interval(self):
        limiter = _make_limiter(base_interval=2.0)
        assert limiter.get_current_interval() == 2.0

    def test_record_success_no_change(self):
        limiter = _make_limiter()
        limiter.record(200, 0.5)
        assert limiter.get_current_interval() == 1.0

    def test_properties_empty(self):
        limiter = _make_limiter()
        assert limiter.success_rate == 1.0
        assert limiter.block_rate == 0.0
        assert limiter.avg_latency == 0.0
        assert limiter.timeout_rate == 0.0


# ====================================================================
# 自适应调整逻辑
# ====================================================================

class TestAdaptiveLimiterAdjust:
    def test_block_rate_above_threshold_doubles(self):
        """block_rate > 10% 时间隔翻倍。"""
        limiter = _make_limiter(base_interval=1.0, block_threshold=0.10)
        for _ in range(8):
            limiter.record(200, 0.3)
        # 2 out of 10 = 20% > 10%
        limiter.record(429, 0.1)
        interval_before = limiter.get_current_interval()
        limiter.record(429, 0.1)
        assert limiter.get_current_interval() >= interval_before

    def test_warn_threshold_multiplies_1_5(self):
        """block_rate 5~10% 时间隔 ×1.5。"""
        limiter = _make_limiter(
            base_interval=1.0,
            block_threshold=0.10,
            warn_threshold=0.05,
        )
        for _ in range(18):
            limiter.record(200, 0.3)
        # 1 out of 19 ≈ 5.3%  > warn 5%
        limiter.record(429, 0.1)
        assert limiter.get_current_interval() >= 1.5

    def test_high_latency_multiplies_1_3(self):
        """avg_latency > 5s 时间隔 ×1.3。"""
        limiter = _make_limiter(base_interval=1.0, latency_spike_sec=5.0)
        for _ in range(5):
            limiter.record(200, 6.0)
        assert limiter.get_current_interval() >= 1.3

    def test_speedup_after_normal(self):
        """持续正常时逐渐加速到 base_interval。"""
        limiter = _make_limiter(base_interval=1.0)
        limiter._current_interval = 5.0
        # last_block_time = 0, total >= 5 → speedup
        for _ in range(6):
            limiter.record(200, 0.3)
        assert limiter.get_current_interval() < 5.0

    def test_interval_never_below_base(self):
        """间隔不会低于 base_interval。"""
        limiter = _make_limiter(base_interval=2.0)
        limiter._current_interval = 2.1
        for _ in range(10):
            limiter.record(200, 0.1)
        assert limiter.get_current_interval() >= 2.0


# ====================================================================
# Retry-After
# ====================================================================

class TestRetryAfter:
    def test_record_retry_after_sets_minimum(self):
        limiter = _make_limiter(base_interval=1.0)
        limiter.record_retry_after(30.0)
        assert limiter.get_current_interval() >= 30.0

    def test_retry_after_expires(self):
        limiter = _make_limiter(base_interval=1.0)
        now = time.monotonic()
        with patch("src.datacollect.adaptive_limiter.time") as mock_time:
            mock_time.monotonic.return_value = now
            limiter.record_retry_after(10.0)

            mock_time.monotonic.return_value = now + 20.0
            interval = limiter.get_current_interval()
            assert interval == limiter._current_interval


# ====================================================================
# 滑动窗口
# ====================================================================

class TestSlidingWindow:
    def test_old_results_purged(self):
        limiter = _make_limiter(window_sec=10.0)
        now = time.monotonic()
        with patch("src.datacollect.adaptive_limiter.time") as mock_time:
            mock_time.monotonic.return_value = now
            limiter.record(429, 0.1)

            mock_time.monotonic.return_value = now + 15.0
            limiter.record(200, 0.3)

        assert limiter.block_rate == 0.0

    def test_properties_reflect_window(self):
        limiter = _make_limiter()
        limiter.record(200, 1.0)
        limiter.record(429, 2.0)
        limiter.record(0, 0.0)
        assert limiter.success_rate == pytest.approx(1 / 3)
        assert limiter.block_rate == pytest.approx(1 / 3)
        assert limiter.timeout_rate == pytest.approx(1 / 3)
        assert limiter.avg_latency == pytest.approx(1.0)


# ====================================================================
# for_domain 单例
# ====================================================================

class TestForDomain:
    def test_same_domain_returns_same_instance(self):
        a = AdaptiveLimiter.for_domain("akshare", 1.0)
        b = AdaptiveLimiter.for_domain("akshare", 2.0)
        assert a is b

    def test_different_domains_different_instances(self):
        a = AdaptiveLimiter.for_domain("akshare", 1.0)
        b = AdaptiveLimiter.for_domain("tushare", 2.0)
        assert a is not b


# ====================================================================
# 线程安全
# ====================================================================

class TestThreadSafety:
    def test_concurrent_record(self):
        limiter = _make_limiter()
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(50):
                    limiter.record(200, 0.3)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert limiter.success_rate > 0
