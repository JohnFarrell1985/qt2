"""Tests for src/datacollect/circuit_breaker.py"""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from src.datacollect.circuit_breaker import CircuitBreaker, CircuitState


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture(autouse=True)
def _cleanup_domain_instances():
    CircuitBreaker.reset_all()
    yield
    CircuitBreaker.reset_all()


def _make_cb(**kwargs) -> CircuitBreaker:
    defaults = {
        "name": "test",
        "failure_threshold": 3,
        "cooldown_sec": 10.0,
        "success_threshold": 2,
    }
    defaults.update(kwargs)
    return CircuitBreaker(**defaults)


# ====================================================================
# 初始状态
# ====================================================================

class TestInitialState:
    def test_starts_closed(self):
        cb = _make_cb()
        assert cb.state == CircuitState.CLOSED

    def test_allows_request_when_closed(self):
        cb = _make_cb()
        assert cb.allow_request() is True

    def test_name_property(self):
        cb = _make_cb(name="akshare")
        assert cb.name == "akshare"


# ====================================================================
# CLOSED → OPEN
# ====================================================================

class TestClosedToOpen:
    def test_opens_after_threshold_failures(self):
        cb = _make_cb(failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_not_open_below_threshold(self):
        cb = _make_cb(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_success_resets_failure_count(self):
        cb = _make_cb(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_blocks_requests_when_open(self):
        cb = _make_cb(failure_threshold=1)
        cb.record_failure()
        assert cb.allow_request() is False


# ====================================================================
# OPEN → HALF_OPEN
# ====================================================================

class TestOpenToHalfOpen:
    def test_transitions_after_cooldown(self):
        cb = _make_cb(failure_threshold=1, cooldown_sec=5.0)
        import time
        now = time.monotonic()

        with patch("src.datacollect.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = now
            cb.record_failure()
            assert cb.state == CircuitState.OPEN

            mock_time.monotonic.return_value = now + 6.0
            assert cb.state == CircuitState.HALF_OPEN

    def test_allows_request_in_half_open(self):
        cb = _make_cb(failure_threshold=1, cooldown_sec=5.0)
        import time
        now = time.monotonic()

        with patch("src.datacollect.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = now
            cb.record_failure()

            mock_time.monotonic.return_value = now + 6.0
            assert cb.allow_request() is True


# ====================================================================
# HALF_OPEN → CLOSED / OPEN
# ====================================================================

class TestHalfOpenTransitions:
    def _enter_half_open(self, cb: CircuitBreaker) -> float:
        import time
        now = time.monotonic()
        return now

    def test_closes_after_success_threshold(self):
        cb = _make_cb(failure_threshold=1, cooldown_sec=5.0, success_threshold=2)
        import time
        now = time.monotonic()

        with patch("src.datacollect.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = now
            cb.record_failure()

            mock_time.monotonic.return_value = now + 6.0
            cb.record_success()
            assert cb.state == CircuitState.HALF_OPEN
            cb.record_success()
            assert cb.state == CircuitState.CLOSED

    def test_reopens_on_failure_with_double_cooldown(self):
        cb = _make_cb(failure_threshold=1, cooldown_sec=5.0, success_threshold=2)
        import time
        now = time.monotonic()

        with patch("src.datacollect.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = now
            cb.record_failure()

            mock_time.monotonic.return_value = now + 6.0
            assert cb.state == CircuitState.HALF_OPEN
            cb.record_failure()
            assert cb.state == CircuitState.OPEN
            assert cb._cooldown_sec == 10.0


# ====================================================================
# force_open / reset
# ====================================================================

class TestManualControl:
    def test_force_open(self):
        cb = _make_cb()
        cb.force_open()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_reset(self):
        cb = _make_cb(failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True


# ====================================================================
# for_domain 单例
# ====================================================================

class TestForDomain:
    def test_same_domain_returns_same_instance(self):
        a = CircuitBreaker.for_domain("akshare", failure_threshold=3)
        b = CircuitBreaker.for_domain("akshare", failure_threshold=5)
        assert a is b

    def test_different_domains(self):
        a = CircuitBreaker.for_domain("akshare")
        b = CircuitBreaker.for_domain("tushare")
        assert a is not b


# ====================================================================
# 边界条件
# ====================================================================

class TestEdgeCases:
    def test_zero_failure_threshold(self):
        """failure_threshold=0 意味着任何失败立即熔断? 实际应 >=1。"""
        cb = CircuitBreaker(name="edge", failure_threshold=0)
        assert cb.state == CircuitState.CLOSED

    def test_success_in_closed_is_noop(self):
        cb = _make_cb()
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_cooldown_doubles_each_half_open_failure(self):
        cb = _make_cb(failure_threshold=1, cooldown_sec=5.0, success_threshold=2)
        import time
        now = time.monotonic()

        with patch("src.datacollect.circuit_breaker.time") as mock_time:
            mock_time.monotonic.return_value = now
            cb.record_failure()  # → OPEN

            mock_time.monotonic.return_value = now + 6.0
            cb.record_failure()  # HALF_OPEN → OPEN, cooldown=10
            assert cb._cooldown_sec == 10.0

            mock_time.monotonic.return_value = now + 17.0
            cb.record_failure()  # HALF_OPEN → OPEN, cooldown=20
            assert cb._cooldown_sec == 20.0


# ====================================================================
# 线程安全
# ====================================================================

class TestThreadSafety:
    def test_concurrent_record(self):
        cb = _make_cb(failure_threshold=100)
        errors: list[Exception] = []

        def record_failures():
            try:
                for _ in range(50):
                    cb.record_failure()
            except Exception as e:
                errors.append(e)

        def record_successes():
            try:
                for _ in range(50):
                    cb.record_success()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=record_failures),
            threading.Thread(target=record_successes),
            threading.Thread(target=record_failures),
            threading.Thread(target=record_successes),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert cb.state in (CircuitState.CLOSED, CircuitState.OPEN)
