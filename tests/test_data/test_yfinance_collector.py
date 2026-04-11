"""Tests for YfinanceCollector"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.datacollect.base import CollectTask
from src.datacollect.collectors.yfinance_collector import (
    YfinanceCollector, TICKER_MAP, _FUNC_MAP,
)


@pytest.fixture
def mock_limiter():
    limiter = MagicMock()
    limiter.acquire.return_value = True
    return limiter


@pytest.fixture
def collector(mock_limiter):
    return YfinanceCollector(limiter=mock_limiter)


class TestTickerMap:
    def test_all_data_types_have_tickers(self):
        for data_type in _FUNC_MAP:
            assert data_type in TICKER_MAP, f"{data_type} missing from TICKER_MAP"

    def test_func_map_methods_exist(self):
        c = YfinanceCollector.__new__(YfinanceCollector)
        for method_name in _FUNC_MAP.values():
            assert hasattr(c, method_name), f"Missing method: {method_name}"


class TestDownload:
    def test_download_returns_rows(self, collector):
        import pandas as pd

        idx = pd.DatetimeIndex(["2026-04-01", "2026-04-02"])
        mock_df = pd.DataFrame(
            {"Open": [100, 101], "High": [102, 103], "Low": [99, 100],
             "Close": [101, 103], "Volume": [1000, 1200]},
            index=idx,
        )
        mock_yf = MagicMock()
        mock_yf.download.return_value = mock_df
        with patch.dict("sys.modules", {"yfinance": mock_yf}):
            rows = collector._download({"TEST": "^TEST"})
        assert isinstance(rows, list)
        assert len(rows) == 1
        assert rows[0]["symbol"] == "TEST"

    def test_download_import_error(self, collector):
        with patch.dict("sys.modules", {"yfinance": None}):
            with patch("builtins.__import__", side_effect=ImportError("no yfinance")):
                with pytest.raises(RuntimeError, match="yfinance 未安装"):
                    collector._download({"TEST": "^TEST"})


class TestCollect:
    def test_missing_func_name_and_data_type(self, collector):
        task = CollectTask(params={})
        with pytest.raises(ValueError, match="无法确定采集方法"):
            collector.collect(task)

    def test_collect_via_data_type(self, collector):
        with patch.object(collector, "fetch_vix", return_value=[{"symbol": "VIX"}]) as mock_fn:
            task = CollectTask(data_type="vix", params={})
            result = collector.collect(task)
            mock_fn.assert_called_once()
            assert result.source == "yfinance"
            assert result.metadata["records_count"] == 1

    def test_collect_via_func_name(self, collector):
        with patch.object(collector, "fetch_gold", return_value=[]) as mock_fn:
            task = CollectTask(params={"func_name": "fetch_gold"})
            collector.collect(task)
            mock_fn.assert_called_once()


class TestHealthCheck:
    def test_healthy(self, collector):
        with patch.object(collector, "fetch_vix", return_value=[{"symbol": "VIX"}]):
            assert collector.health_check() is True

    def test_empty(self, collector):
        with patch.object(collector, "fetch_vix", return_value=[]):
            assert collector.health_check() is False

    def test_exception(self, collector):
        with patch.object(collector, "fetch_vix", side_effect=RuntimeError("fail")):
            assert collector.health_check() is False


class TestFuncForDataType:
    def test_known(self):
        assert YfinanceCollector.func_for_data_type("vix") == "fetch_vix"
        assert YfinanceCollector.func_for_data_type("gold") == "fetch_gold"

    def test_unknown(self):
        assert YfinanceCollector.func_for_data_type("nonexistent") is None
