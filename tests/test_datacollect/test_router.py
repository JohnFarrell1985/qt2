"""CollectRouter 单元测试

测试 src/datacollect/router.py:
- register 添加数据源
- route 调用首个健康源
- 自动降级: 首个源失败时调用下一个
- SourceHealth.is_healthy 追踪
"""
import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from dataclasses import dataclass
from typing import Any

from src.datacollect.router import CollectRouter, SourceHealth


@dataclass
class _MockResult:
    """模拟 CollectResult, 带 success 属性"""
    source: str
    data: Any = None
    success: bool = True


@pytest.fixture()
def router():
    return CollectRouter()


@pytest.fixture()
def _mock_settings():
    """Mock settings.datacollect 的 circuit breaker 配置"""
    mock_dc = MagicMock()
    mock_dc.circuit_breaker_threshold = 3
    mock_dc.circuit_breaker_cooldown = 60
    mock_settings = MagicMock()
    mock_settings.datacollect = mock_dc
    with patch("src.datacollect.router.settings", mock_settings):
        yield mock_settings


class TestRegister:

    @pytest.mark.timeout(30)
    def test_register_adds_source(self, router: CollectRouter):
        handler = MagicMock(return_value=_MockResult(source="test"))
        router.register("src_a", handler)
        assert "src_a" in router._sources
        assert "src_a" in router._health
        assert "src_a" in router._chain

    @pytest.mark.timeout(30)
    def test_register_multiple_sources(self, router: CollectRouter):
        router.register("a", MagicMock(), priority=1)
        router.register("b", MagicMock(), priority=2)
        assert len(router._sources) == 2

    @pytest.mark.timeout(30)
    def test_register_creates_health_tracker(self, router: CollectRouter):
        router.register("src_b", MagicMock())
        health = router._health["src_b"]
        assert isinstance(health, SourceHealth)
        assert health.success_count == 0
        assert health.fail_count == 0


class TestRoute:

    @pytest.mark.timeout(30)
    @pytest.mark.usefixtures("_mock_settings")
    def test_route_calls_first_healthy_source(self, router: CollectRouter):
        expected = _MockResult(source="primary", success=True)
        handler_a = MagicMock(return_value=expected)
        handler_b = MagicMock(return_value=_MockResult(source="backup"))
        router.register("primary", handler_a, priority=1)
        router.register("backup", handler_b, priority=2)

        result = router.route(query="test")
        assert result is expected
        handler_a.assert_called_once_with(query="test")
        handler_b.assert_not_called()

    @pytest.mark.timeout(30)
    @pytest.mark.usefixtures("_mock_settings")
    def test_route_returns_none_when_all_fail(self, router: CollectRouter):
        handler = MagicMock(side_effect=Exception("fail"))
        router.register("only", handler, priority=1)
        result = router.route()
        assert result is None

    @pytest.mark.timeout(30)
    @pytest.mark.usefixtures("_mock_settings")
    def test_route_skips_unsuccessful_result(self, router: CollectRouter):
        bad_result = _MockResult(source="bad", success=False)
        good_result = _MockResult(source="good", success=True)
        handler_a = MagicMock(return_value=bad_result)
        handler_b = MagicMock(return_value=good_result)
        router.register("bad_src", handler_a, priority=1)
        router.register("good_src", handler_b, priority=2)

        result = router.route()
        assert result is good_result


class TestFallback:

    @pytest.mark.timeout(30)
    @pytest.mark.usefixtures("_mock_settings")
    def test_fallback_on_exception(self, router: CollectRouter):
        fallback_result = _MockResult(source="fallback", success=True)
        handler_a = MagicMock(side_effect=RuntimeError("primary down"))
        handler_b = MagicMock(return_value=fallback_result)
        router.register("primary", handler_a, priority=1)
        router.register("fallback", handler_b, priority=2)

        result = router.route()
        assert result is fallback_result
        handler_a.assert_called_once()
        handler_b.assert_called_once()

    @pytest.mark.timeout(30)
    @pytest.mark.usefixtures("_mock_settings")
    def test_fallback_records_failure(self, router: CollectRouter):
        handler = MagicMock(side_effect=RuntimeError("down"))
        router.register("flaky", handler, priority=1)
        router.route()
        health = router._health["flaky"]
        assert health.fail_count == 1
        assert health.consecutive_fails == 1

    @pytest.mark.timeout(30)
    @pytest.mark.usefixtures("_mock_settings")
    def test_success_records_health(self, router: CollectRouter):
        handler = MagicMock(return_value=_MockResult(source="ok", success=True))
        router.register("ok_src", handler, priority=1)
        router.route()
        health = router._health["ok_src"]
        assert health.success_count == 1
        assert health.consecutive_fails == 0


class TestSourceHealth:

    @pytest.mark.timeout(30)
    @pytest.mark.usefixtures("_mock_settings")
    def test_new_source_is_healthy(self):
        h = SourceHealth("test")
        assert h.is_healthy is True

    @pytest.mark.timeout(30)
    @pytest.mark.usefixtures("_mock_settings")
    def test_below_threshold_is_healthy(self):
        h = SourceHealth("test")
        h.record_failure()
        h.record_failure()
        assert h.is_healthy is True

    @pytest.mark.timeout(30)
    @pytest.mark.usefixtures("_mock_settings")
    def test_at_threshold_within_cooldown_unhealthy(self):
        h = SourceHealth("test")
        for _ in range(3):
            h.record_failure()
        assert h.is_healthy is False

    @pytest.mark.timeout(30)
    @pytest.mark.usefixtures("_mock_settings")
    def test_at_threshold_after_cooldown_healthy(self):
        h = SourceHealth("test")
        for _ in range(3):
            h.record_failure()
        h.last_fail_ts = time.time() - 120
        assert h.is_healthy is True
        assert h.consecutive_fails == 0

    @pytest.mark.timeout(30)
    @pytest.mark.usefixtures("_mock_settings")
    def test_record_success_resets_consecutive(self):
        h = SourceHealth("test")
        h.record_failure()
        h.record_failure()
        h.record_success()
        assert h.consecutive_fails == 0
        assert h.success_count == 1


class TestGetHealthReport:

    @pytest.mark.timeout(30)
    @pytest.mark.usefixtures("_mock_settings")
    def test_health_report(self, router: CollectRouter):
        handler_a = MagicMock(return_value=_MockResult(source="a", success=True))
        handler_b = MagicMock(side_effect=Exception("fail"))
        router.register("src_a", handler_a, priority=1)
        router.register("src_b", handler_b, priority=2)

        router.route()

        report = router.get_health_report()
        assert len(report) == 2
        names = {r["name"] for r in report}
        assert names == {"src_a", "src_b"}
