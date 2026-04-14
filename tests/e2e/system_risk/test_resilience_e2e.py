"""E2E: 系统弹性 — CircuitBreaker + DegradationManager + resilient_call

真实场景: 用 DB 查询作为受保护调用, 测试熔断/恢复/降级。
"""
import time

import pytest
from sqlalchemy import text

from src.common.resilience import (
    CircuitBreaker, CircuitState, CircuitOpenError,
    DegradationManager, DegradationLevel,
    resilient_call,
)


class TestCircuitBreakerWithRealDB:
    """用真实 DB 连接验证 CircuitBreaker"""

    def test_successful_calls_stay_closed(self, pg_engine):
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=1.0)

        def query_db():
            with pg_engine.connect() as conn:
                return conn.execute(text("SELECT count(*) FROM stocks")).scalar()

        result = cb.call(query_db)
        assert result > 0
        assert cb.state == CircuitState.CLOSED

    def test_failures_trip_breaker(self):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.5)
        call_count = 0

        def failing_func():
            nonlocal call_count
            call_count += 1
            raise ConnectionError("DB down")

        for _ in range(2):
            with pytest.raises(ConnectionError):
                cb.call(failing_func)

        assert cb.state == CircuitState.OPEN
        with pytest.raises(CircuitOpenError):
            cb.call(failing_func)

    def test_half_open_recovery(self, pg_engine):
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.3)

        def fail():
            raise ConnectionError("fail")

        for _ in range(2):
            with pytest.raises(ConnectionError):
                cb.call(fail)
        assert cb.state == CircuitState.OPEN

        time.sleep(0.4)
        assert cb.state == CircuitState.HALF_OPEN

        def query_db():
            with pg_engine.connect() as conn:
                return conn.execute(text("SELECT 1")).scalar()

        result = cb.call(query_db)
        assert result == 1
        assert cb.state == CircuitState.CLOSED

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=100)
        try:
            cb.call(lambda: (_ for _ in ()).throw(RuntimeError("x")))
        except RuntimeError:
            pass

        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED


class TestDegradationManagerE2E:

    def setup_method(self):
        DegradationManager._reset_singleton()

    def teardown_method(self):
        DegradationManager._reset_singleton()

    def test_singleton(self):
        dm1 = DegradationManager()
        dm2 = DegradationManager()
        assert dm1 is dm2

    def test_normal_all_services_available(self):
        dm = DegradationManager()
        assert dm.level == DegradationLevel.NORMAL
        for svc in ("llm", "data", "trade", "backtest", "api"):
            assert dm.is_available(svc), f"{svc} should be available in NORMAL"

    def test_degraded_llm(self):
        dm = DegradationManager()
        dm.set_level(DegradationLevel.DEGRADED_LLM, "LLM API timeout")
        assert not dm.is_available("llm")
        assert dm.is_available("data")
        assert dm.is_available("trade")

    def test_degraded_data(self):
        dm = DegradationManager()
        dm.set_level(DegradationLevel.DEGRADED_DATA, "Data source down")
        assert dm.is_available("llm")
        assert not dm.is_available("data")
        assert dm.is_available("trade")
        assert not dm.is_available("backtest")

    def test_emergency_nothing_available(self):
        dm = DegradationManager()
        dm.set_level(DegradationLevel.EMERGENCY, "Total outage")
        for svc in ("llm", "data", "trade", "backtest", "api"):
            assert not dm.is_available(svc)

    def test_listener_callback(self):
        dm = DegradationManager()
        transitions = []
        dm.on_change(lambda old, new, reason: transitions.append((old, new, reason)))
        dm.set_level(DegradationLevel.DEGRADED_LLM, "test")
        assert len(transitions) == 1
        assert transitions[0] == (DegradationLevel.NORMAL, DegradationLevel.DEGRADED_LLM, "test")


class TestResilientCallE2E:

    def test_success_with_real_db(self, pg_engine):
        def query():
            with pg_engine.connect() as conn:
                return conn.execute(text("SELECT count(*) FROM trading_date")).scalar()

        result = resilient_call(query, fallback=-1)
        assert result > 0

    def test_fallback_on_failure(self):
        call_count = 0

        def bad_func():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("kaboom")

        result = resilient_call(bad_func, fallback="default_value", max_retries=2)
        assert result == "default_value"
        assert call_count == 2

    def test_with_circuit_breaker(self, pg_engine):
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=10)

        def query():
            with pg_engine.connect() as conn:
                return conn.execute(text("SELECT 1")).scalar()

        result = resilient_call(query, fallback=None, breaker=cb, max_retries=2)
        assert result == 1
        assert cb.state == CircuitState.CLOSED

    def test_breaker_open_returns_fallback(self):
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=100)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

        result = resilient_call(
            lambda: 42, fallback="fallback", breaker=cb, max_retries=1,
        )
        assert result == "fallback"
