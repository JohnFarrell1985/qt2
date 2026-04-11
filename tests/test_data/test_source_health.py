"""Tests for src/datacollect/health.py"""
from __future__ import annotations

import threading

import pytest

from src.datacollect.health import SourceHealthDashboard, SourceHealthMetrics


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture(autouse=True)
def _cleanup_singleton():
    SourceHealthDashboard.reset_instance()
    yield
    SourceHealthDashboard.reset_instance()


@pytest.fixture()
def dashboard() -> SourceHealthDashboard:
    return SourceHealthDashboard()


# ====================================================================
# SourceHealthMetrics 属性
# ====================================================================

class TestMetricsProperties:
    def test_empty_metrics(self):
        m = SourceHealthMetrics(domain="test")
        assert m.success_rate == 1.0
        assert m.avg_latency_ms == 0.0
        assert m.health_score == pytest.approx(100.0)

    def test_success_rate(self):
        m = SourceHealthMetrics(
            domain="test", total_requests=10, success_count=8,
        )
        assert m.success_rate == pytest.approx(0.8)

    def test_avg_latency_ms(self):
        m = SourceHealthMetrics(
            domain="test", total_requests=4, latency_sum=2.0,
        )
        assert m.avg_latency_ms == pytest.approx(500.0)

    def test_health_score_all_success_fast(self):
        m = SourceHealthMetrics(
            domain="test",
            total_requests=10,
            success_count=10,
            latency_sum=1.0,
            circuit_state="closed",
        )
        assert m.health_score == pytest.approx(100.0)

    def test_health_score_open_circuit(self):
        m = SourceHealthMetrics(
            domain="test",
            total_requests=10,
            success_count=10,
            latency_sum=1.0,
            circuit_state="open",
        )
        assert m.health_score == pytest.approx(80.0)

    def test_health_score_half_open(self):
        m = SourceHealthMetrics(
            domain="test",
            total_requests=10,
            success_count=10,
            latency_sum=1.0,
            circuit_state="half_open",
        )
        assert m.health_score == pytest.approx(90.0)

    def test_health_score_high_latency(self):
        m = SourceHealthMetrics(
            domain="test",
            total_requests=10,
            success_count=10,
            latency_sum=50.0,
            circuit_state="closed",
        )
        assert m.health_score < 100.0
        assert m.health_score >= 60.0

    def test_health_score_zero_success(self):
        m = SourceHealthMetrics(
            domain="test",
            total_requests=10,
            success_count=0,
            block_count=10,
            latency_sum=1.0,
            circuit_state="open",
        )
        assert m.health_score < 30.0


# ====================================================================
# Dashboard 记录
# ====================================================================

class TestDashboardRecord:
    def test_record_success(self, dashboard: SourceHealthDashboard):
        dashboard.record_request("d", 200, 0.3)
        h = dashboard.get_health("d")
        assert h.total_requests == 1
        assert h.success_count == 1
        assert h.latency_sum == pytest.approx(0.3)

    def test_record_block(self, dashboard: SourceHealthDashboard):
        dashboard.record_request("d", 429, 0.1)
        h = dashboard.get_health("d")
        assert h.block_count == 1

    def test_record_timeout(self, dashboard: SourceHealthDashboard):
        dashboard.record_request("d", 0, 0.0)
        h = dashboard.get_health("d")
        assert h.timeout_count == 1

    def test_record_error(self, dashboard: SourceHealthDashboard):
        dashboard.record_request("d", 500, 1.0)
        h = dashboard.get_health("d")
        assert h.error_count == 1

    def test_record_403_as_block(self, dashboard: SourceHealthDashboard):
        dashboard.record_request("d", 403, 0.2)
        h = dashboard.get_health("d")
        assert h.block_count == 1


# ====================================================================
# 状态更新
# ====================================================================

class TestUpdateState:
    def test_update_circuit_state(self, dashboard: SourceHealthDashboard):
        dashboard.update_circuit_state("d", "open")
        h = dashboard.get_health("d")
        assert h.circuit_state == "open"

    def test_update_interval(self, dashboard: SourceHealthDashboard):
        dashboard.update_interval("d", 2.5)
        h = dashboard.get_health("d")
        assert h.current_interval == pytest.approx(2.5)


# ====================================================================
# 查询
# ====================================================================

class TestQueries:
    def test_get_health_unknown_domain(self, dashboard: SourceHealthDashboard):
        h = dashboard.get_health("unknown")
        assert h.domain == "unknown"
        assert h.total_requests == 0

    def test_get_all_health(self, dashboard: SourceHealthDashboard):
        dashboard.record_request("a", 200, 0.3)
        dashboard.record_request("b", 200, 0.5)
        all_h = dashboard.get_all_health()
        assert "a" in all_h
        assert "b" in all_h

    def test_get_ranked_sources(self, dashboard: SourceHealthDashboard):
        dashboard.record_request("bad", 429, 0.1)
        dashboard.update_circuit_state("bad", "open")
        dashboard.record_request("good", 200, 0.1)

        ranked = dashboard.get_ranked_sources()
        assert len(ranked) == 2
        assert ranked[0].domain == "good"
        assert ranked[1].domain == "bad"

    def test_get_health_returns_copy(self, dashboard: SourceHealthDashboard):
        dashboard.record_request("d", 200, 0.3)
        h1 = dashboard.get_health("d")
        h1.total_requests = 999
        h2 = dashboard.get_health("d")
        assert h2.total_requests == 1


# ====================================================================
# 重置
# ====================================================================

class TestReset:
    def test_reset_domain(self, dashboard: SourceHealthDashboard):
        dashboard.record_request("d", 200, 0.3)
        dashboard.reset("d")
        h = dashboard.get_health("d")
        assert h.total_requests == 0

    def test_reset_unknown_is_noop(self, dashboard: SourceHealthDashboard):
        dashboard.reset("unknown")


# ====================================================================
# 单例
# ====================================================================

class TestSingleton:
    def test_instance_returns_same(self):
        a = SourceHealthDashboard.instance()
        b = SourceHealthDashboard.instance()
        assert a is b

    def test_reset_instance_creates_new(self):
        a = SourceHealthDashboard.instance()
        SourceHealthDashboard.reset_instance()
        b = SourceHealthDashboard.instance()
        assert a is not b


# ====================================================================
# 线程安全
# ====================================================================

class TestThreadSafety:
    def test_concurrent_record(self, dashboard: SourceHealthDashboard):
        errors: list[Exception] = []

        def worker(domain: str):
            try:
                for _ in range(50):
                    dashboard.record_request(domain, 200, 0.3)
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=worker, args=(f"d{i}",))
            for i in range(4)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        all_h = dashboard.get_all_health()
        assert len(all_h) == 4
        for m in all_h.values():
            assert m.total_requests == 50
