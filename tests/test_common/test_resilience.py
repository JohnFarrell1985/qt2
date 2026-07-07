"""Tests for src/common/resilience.py"""
import time
import pytest

from src.common.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    CircuitState,
    DegradationLevel,
    DegradationManager,
    resilient_call,
)


@pytest.fixture(autouse=True)
def reset_degradation():
    """Reset singleton between tests."""
    DegradationManager._reset_singleton()
    yield
    DegradationManager._reset_singleton()


# ---- CircuitBreaker ----

class TestCircuitBreaker:
    def test_initial_state_closed(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.5)
        assert cb.state == CircuitState.CLOSED

    def test_stays_closed_on_success(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=0.5)
        result = cb.call(lambda: 42)
        assert result == 42
        assert cb.state == CircuitState.CLOSED

    def test_opens_after_threshold_failures(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        for _ in range(3):
            with pytest.raises(ValueError):
                cb.call(_failing_func)
        assert cb.state == CircuitState.OPEN

    def test_open_rejects_calls(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(_failing_func)
        with pytest.raises(CircuitOpenError):
            cb.call(lambda: 1)

    def test_half_open_after_timeout(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(_failing_func)
        assert cb.state == CircuitState.OPEN
        time.sleep(0.1)
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(_failing_func)
        time.sleep(0.1)
        result = cb.call(lambda: "ok")
        assert result == "ok"
        assert cb.state == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.05)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(_failing_func)
        time.sleep(0.1)
        assert cb.state == CircuitState.HALF_OPEN
        with pytest.raises(ValueError):
            cb.call(_failing_func)
        assert cb.state == CircuitState.OPEN

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
        for _ in range(2):
            with pytest.raises(ValueError):
                cb.call(_failing_func)
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)
        with pytest.raises(ValueError):
            cb.call(_failing_func)
        with pytest.raises(ValueError):
            cb.call(_failing_func)
        cb.call(lambda: "ok")
        with pytest.raises(ValueError):
            cb.call(_failing_func)
        assert cb.state == CircuitState.CLOSED


# ---- DegradationManager ----

class TestDegradationManager:
    def test_singleton(self):
        dm1 = DegradationManager()
        dm2 = DegradationManager()
        assert dm1 is dm2

    def test_default_normal(self):
        dm = DegradationManager()
        assert dm.level == DegradationLevel.NORMAL

    def test_set_level(self):
        dm = DegradationManager()
        dm.set_level(DegradationLevel.DEGRADED_DATA, reason="data source down")
        assert dm.level == DegradationLevel.DEGRADED_DATA

    def test_is_available_normal(self):
        dm = DegradationManager()
        assert dm.is_available("data") is True
        assert dm.is_available("trade") is True

    def test_is_available_degraded_data(self):
        dm = DegradationManager()
        dm.set_level(DegradationLevel.DEGRADED_DATA)
        assert dm.is_available("data") is False
        assert dm.is_available("trade") is True

    def test_is_available_degraded_trade(self):
        dm = DegradationManager()
        dm.set_level(DegradationLevel.DEGRADED_TRADE)
        assert dm.is_available("trade") is False
        assert dm.is_available("data") is True

    def test_is_available_emergency(self):
        dm = DegradationManager()
        dm.set_level(DegradationLevel.EMERGENCY)
        assert dm.is_available("data") is False
        assert dm.is_available("trade") is False

    def test_on_change_callback(self):
        dm = DegradationManager()
        events = []
        dm.on_change(lambda old, new, reason: events.append((old, new, reason)))
        dm.set_level(DegradationLevel.DEGRADED_DATA, "test")
        assert len(events) == 1
        assert events[0] == (DegradationLevel.NORMAL, DegradationLevel.DEGRADED_DATA, "test")

    def test_no_callback_on_same_level(self):
        dm = DegradationManager()
        events = []
        dm.on_change(lambda old, new, reason: events.append(1))
        dm.set_level(DegradationLevel.NORMAL)
        assert len(events) == 0

    def test_reset(self):
        dm = DegradationManager()
        dm.set_level(DegradationLevel.EMERGENCY)
        dm.on_change(lambda *a: None)
        dm.reset()
        assert dm.level == DegradationLevel.NORMAL


# ---- resilient_call ----

class TestResilientCall:
    def test_success(self):
        result = resilient_call(lambda: 42)
        assert result == 42

    def test_fallback_on_failure(self):
        result = resilient_call(_failing_func, fallback="default", max_retries=1)
        assert result == "default"

    def test_with_breaker_success(self):
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=60.0)
        result = resilient_call(lambda: "ok", breaker=cb)
        assert result == "ok"

    def test_with_breaker_open_uses_fallback(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=60.0)
        for _ in range(2):
            cb.record_failure()
        result = resilient_call(lambda: "ok", fallback="fallback", breaker=cb)
        assert result == "fallback"

    def test_retries_before_fallback(self):
        call_count = {"n": 0}

        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ValueError("not yet")
            return "success"

        result = resilient_call(flaky, fallback="fail", max_retries=3)
        assert result == "success"
        assert call_count["n"] == 3


def _failing_func():
    raise ValueError("intentional failure")
