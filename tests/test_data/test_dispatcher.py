"""Tests for src/datacollect/dispatcher.py"""
from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from src.datacollect.base import BaseCollector, CollectResult, CollectTask
from src.datacollect.dispatcher import FallbackDispatcher, _DATA_TYPE_FUNC
from src.datacollect.registry import DataSourceDef, DataSourceRegistry


# ====================================================================
# Fixtures
# ====================================================================

def _make_source_def(
    name: str,
    collector_class: str = "fake.module.FakeCollector",
    package: str | None = None,
    capabilities: list[str] | None = None,
    enabled: bool = True,
    priority: int = 1,
) -> DataSourceDef:
    return DataSourceDef(
        name=name,
        collector_class=collector_class,
        package=package,
        capabilities=capabilities or [],
        enabled=enabled,
        priority=priority,
    )


def _make_collect_result(source: str, data=None) -> CollectResult:
    return CollectResult(source=source, data=data or pd.DataFrame({"a": [1]}))


class FakeCollector(BaseCollector):
    SOURCE = "fake"

    def collect(self, task: CollectTask) -> CollectResult:
        return _make_collect_result(self.SOURCE)

    def health_check(self) -> bool:
        return True


class FailCollector(BaseCollector):
    SOURCE = "fail"

    def collect(self, task: CollectTask) -> CollectResult:
        raise RuntimeError("always fails")

    def health_check(self) -> bool:
        return False


@pytest.fixture
def registry():
    reg = DataSourceRegistry()
    reg.register("source_a", _make_source_def(
        "source_a", collector_class="tests.test_data.test_dispatcher.FakeCollector",
        priority=1, capabilities=["daily_kline", "stock_list"],
    ))
    reg.register("source_b", _make_source_def(
        "source_b", collector_class="tests.test_data.test_dispatcher.FakeCollector",
        priority=2, capabilities=["daily_kline"],
    ))
    reg.set_fallback_chain("daily_kline", ["source_a", "source_b"])
    reg.set_fallback_chain("stock_list", ["source_a"])
    return reg


@pytest.fixture
def dispatcher(registry):
    return FallbackDispatcher(registry=registry)


# ====================================================================
# __init__
# ====================================================================

class TestInit:

    def test_custom_registry(self, registry):
        d = FallbackDispatcher(registry=registry)
        assert d.registry is registry

    @patch("src.datacollect.dispatcher.DataSourceRegistry.from_json")
    def test_default_registry(self, mock_from_json):
        mock_from_json.return_value = DataSourceRegistry()
        FallbackDispatcher()
        mock_from_json.assert_called_once()


# ====================================================================
# _get_collector
# ====================================================================

class TestGetCollector:

    def test_caches_collector(self, dispatcher):
        c1 = dispatcher._get_collector("source_a")
        c2 = dispatcher._get_collector("source_a")
        assert c1 is c2
        assert isinstance(c1, FakeCollector)

    def test_unknown_source(self, dispatcher):
        assert dispatcher._get_collector("nonexistent") is None

    def test_no_collector_class(self, dispatcher, registry):
        registry.register("bare", _make_source_def("bare", collector_class=None))
        assert dispatcher._get_collector("bare") is None

    def test_missing_package(self, dispatcher, registry):
        registry.register("needs_pkg", _make_source_def(
            "needs_pkg", package="nonexistent_package_xyz",
        ))
        assert dispatcher._get_collector("needs_pkg") is None

    def test_bad_import_path(self, dispatcher, registry):
        registry.register("bad_path", _make_source_def(
            "bad_path", collector_class="no.such.module.Cls",
        ))
        assert dispatcher._get_collector("bad_path") is None


# ====================================================================
# _resolve_func_name
# ====================================================================

class TestResolveFuncName:

    def test_known_mapping(self):
        assert FallbackDispatcher._resolve_func_name("daily_kline", "eastmoney") == "fetch_kline"
        assert FallbackDispatcher._resolve_func_name("stock_list", "akshare") == "stock_zh_a_spot_em"
        assert FallbackDispatcher._resolve_func_name("realtime", "eastmoney") == "fetch_realtime"

    def test_unknown_data_type(self):
        assert FallbackDispatcher._resolve_func_name("unknown_type", "eastmoney") is None

    def test_unknown_source_for_type(self):
        assert FallbackDispatcher._resolve_func_name("daily_kline", "unknown_src") is None


# ====================================================================
# fetch
# ====================================================================

class TestFetch:

    def test_no_fallback_chain(self, dispatcher):
        with pytest.raises(RuntimeError, match="未配置.*降级链"):
            dispatcher.fetch("nonexistent_type")

    def test_success_on_first_source(self, dispatcher):
        with patch.object(FakeCollector, "collect", return_value=_make_collect_result("source_a")):
            with patch.object(FallbackDispatcher, "_resolve_func_name", return_value="some_func"):
                result = dispatcher.fetch("daily_kline")
        assert isinstance(result, CollectResult)
        assert result.source == "source_a"

    def test_fallback_to_second(self, dispatcher):
        call_count = {"n": 0}

        def _collect(self, task):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("first fails")
            return _make_collect_result("source_b")

        with patch.object(FakeCollector, "collect", _collect):
            with patch.object(FallbackDispatcher, "_resolve_func_name", return_value="some_func"):
                result = dispatcher.fetch("daily_kline")
        assert result.source == "source_b"

    def test_all_fail_raises(self, dispatcher, registry):
        registry.register("fail_a", _make_source_def(
            "fail_a", collector_class="tests.test_data.test_dispatcher.FailCollector",
            priority=1,
        ))
        registry.register("fail_b", _make_source_def(
            "fail_b", collector_class="tests.test_data.test_dispatcher.FailCollector",
            priority=2,
        ))
        registry.set_fallback_chain("test_fail", ["fail_a", "fail_b"])

        with patch.object(FallbackDispatcher, "_resolve_func_name", return_value="some_func"):
            with pytest.raises(RuntimeError, match="所有数据源均失败"):
                dispatcher.fetch("test_fail")

    def test_skip_empty_result(self, dispatcher):
        call_count = {"n": 0}

        def _collect(self, task):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return CollectResult(source="source_a", data=pd.DataFrame())
            return _make_collect_result("source_b")

        with patch.object(FakeCollector, "collect", _collect):
            with patch.object(FallbackDispatcher, "_resolve_func_name", return_value="some_func"):
                result = dispatcher.fetch("daily_kline")
        assert result.source == "source_b"

    def test_skip_source_without_func_mapping(self, dispatcher, registry):
        registry.set_fallback_chain("unmapped_type", ["source_a"])
        with pytest.raises(RuntimeError, match="所有数据源均失败"):
            dispatcher.fetch("unmapped_type")


# ====================================================================
# check_availability
# ====================================================================

class TestCheckAvailability:

    def test_returns_health_status(self, dispatcher):
        result = dispatcher.check_availability()
        assert isinstance(result, dict)
        for v in result.values():
            assert isinstance(v, bool)

    def test_collector_not_available(self, dispatcher, registry):
        registry.register("no_pkg", _make_source_def(
            "no_pkg", package="nonexistent_pkg_xyz", priority=10,
        ))
        result = dispatcher.check_availability()
        assert result.get("no_pkg") is False

    def test_health_check_exception(self, dispatcher, registry):
        registry.register("err_src", _make_source_def(
            "err_src",
            collector_class="tests.test_data.test_dispatcher.FailCollector",
            priority=10,
        ))
        result = dispatcher.check_availability()
        assert result.get("err_src") is False


# ====================================================================
# registry property
# ====================================================================

class TestRegistryProperty:

    def test_returns_registry(self, dispatcher, registry):
        assert dispatcher.registry is registry


# ====================================================================
# _DATA_TYPE_FUNC completeness
# ====================================================================

class TestDataTypeFuncMapping:

    def test_eastmoney_mappings_exist(self):
        assert "stock_list" in _DATA_TYPE_FUNC
        assert "eastmoney" in _DATA_TYPE_FUNC["stock_list"]
        assert "daily_kline" in _DATA_TYPE_FUNC
        assert "eastmoney" in _DATA_TYPE_FUNC["daily_kline"]
        assert "realtime" in _DATA_TYPE_FUNC
        assert "eastmoney" in _DATA_TYPE_FUNC["realtime"]

    def test_all_data_types_have_at_least_one_source(self):
        for data_type, sources in _DATA_TYPE_FUNC.items():
            assert len(sources) >= 1, f"{data_type} has no source mappings"
