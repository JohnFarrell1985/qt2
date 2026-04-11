"""Tests for src/datacollect/collectors/pytdx_collector.py"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.datacollect.base import CollectResult, CollectTask
from src.datacollect.collectors.pytdx_collector import (
    KLINE_CATEGORY,
    MARKET_SH,
    MARKET_SZ,
    PytdxCollector,
)


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture
def mock_limiter():
    limiter = MagicMock()
    limiter.acquire.return_value = True
    return limiter


@pytest.fixture
def collector(mock_limiter):
    return PytdxCollector(limiter=mock_limiter)


@pytest.fixture
def mock_api():
    """构造模拟的 TdxHq_API 实例。"""
    api = MagicMock()
    api.connect.return_value = api
    api.disconnect.return_value = None
    return api


@pytest.fixture
def mock_best_ip():
    return {"ip": "119.147.212.81", "port": 7709}


# ====================================================================
# Constants
# ====================================================================

class TestConstants:

    def test_market_values(self):
        assert MARKET_SZ == 0
        assert MARKET_SH == 1

    def test_kline_categories(self):
        assert KLINE_CATEGORY["daily"] == 4
        assert KLINE_CATEGORY["5min"] == 0
        assert KLINE_CATEGORY["1min"] == 7


# ====================================================================
# __init__
# ====================================================================

class TestInit:

    def test_custom_limiter(self, mock_limiter):
        c = PytdxCollector(limiter=mock_limiter)
        assert c.limiter is mock_limiter

    @patch("src.datacollect.collectors.pytdx_collector.TokenBucketLimiter")
    def test_default_limiter(self, mock_tbl):
        mock_tbl.for_domain.return_value = MagicMock()
        c = PytdxCollector()
        mock_tbl.for_domain.assert_called_once()

    def test_source_name(self, collector):
        assert collector.SOURCE == "pytdx"

    def test_best_ip_initially_none(self, collector):
        assert collector._best_ip is None


# ====================================================================
# _select_best_ip
# ====================================================================

class TestSelectBestIp:

    def test_caches_result(self, collector, mock_best_ip):
        with patch.dict("sys.modules", {"pytdx": MagicMock(), "pytdx.util": MagicMock(), "pytdx.util.best_ip": MagicMock()}):
            import sys
            sys.modules["pytdx.util.best_ip"].select_best_ip = MagicMock(return_value=mock_best_ip)

            ip1 = collector._select_best_ip()
            ip2 = collector._select_best_ip()
            assert ip1 is ip2
            sys.modules["pytdx.util.best_ip"].select_best_ip.assert_called_once()

    def test_returns_ip_dict(self, collector, mock_best_ip):
        with patch.dict("sys.modules", {"pytdx": MagicMock(), "pytdx.util": MagicMock(), "pytdx.util.best_ip": MagicMock()}):
            import sys
            sys.modules["pytdx.util.best_ip"].select_best_ip = MagicMock(return_value=mock_best_ip)

            result = collector._select_best_ip()
            assert result["ip"] == "119.147.212.81"
            assert result["port"] == 7709


# ====================================================================
# _connect_api
# ====================================================================

class TestConnectApi:

    def test_connects_to_best_ip(self, collector, mock_api, mock_best_ip):
        collector._best_ip = mock_best_ip

        with patch.dict("sys.modules", {"pytdx": MagicMock(), "pytdx.hq": MagicMock()}):
            import sys
            sys.modules["pytdx.hq"].TdxHq_API = MagicMock(return_value=mock_api)

            api = collector._connect_api()
            mock_api.connect.assert_called_once_with("119.147.212.81", 7709)
            assert api is mock_api


# ====================================================================
# get_security_bars
# ====================================================================

class TestGetSecurityBars:

    def test_returns_dataframe(self, collector, mock_api, mock_best_ip):
        collector._best_ip = mock_best_ip
        fake_df = pd.DataFrame({"open": [10.0], "close": [10.5]})
        mock_api.get_security_bars.return_value = fake_df

        with patch.object(collector, "_connect_api", return_value=mock_api):
            df = collector.get_security_bars("600000", MARKET_SH, category=9, count=100)

        assert len(df) == 1
        mock_api.get_security_bars.assert_called_once_with(9, MARKET_SH, "600000", 0, 100)
        mock_api.disconnect.assert_called_once()

    def test_empty_result(self, collector, mock_api):
        mock_api.get_security_bars.return_value = None

        with patch.object(collector, "_connect_api", return_value=mock_api):
            df = collector.get_security_bars("600000", MARKET_SH)

        assert isinstance(df, pd.DataFrame)
        assert df.empty

    def test_disconnect_on_error(self, collector, mock_api):
        mock_api.get_security_bars.side_effect = Exception("network error")

        with patch.object(collector, "_connect_api", return_value=mock_api):
            with pytest.raises(Exception, match="network error"):
                collector.get_security_bars("600000", MARKET_SH)
        mock_api.disconnect.assert_called_once()

    def test_limiter_acquire_called(self, collector, mock_limiter, mock_api):
        mock_api.get_security_bars.return_value = pd.DataFrame({"a": [1]})

        with patch.object(collector, "_connect_api", return_value=mock_api):
            collector.get_security_bars("600000", MARKET_SH)
        mock_limiter.acquire.assert_called_once()


# ====================================================================
# get_security_quotes
# ====================================================================

class TestGetSecurityQuotes:

    def test_returns_dataframe(self, collector, mock_api):
        fake_df = pd.DataFrame({"code": ["600000"], "price": [10.5]})
        mock_api.get_security_quotes.return_value = fake_df

        with patch.object(collector, "_connect_api", return_value=mock_api):
            df = collector.get_security_quotes([(MARKET_SH, "600000")])

        assert len(df) == 1
        mock_api.disconnect.assert_called_once()

    def test_empty_result(self, collector, mock_api):
        mock_api.get_security_quotes.return_value = pd.DataFrame()

        with patch.object(collector, "_connect_api", return_value=mock_api):
            df = collector.get_security_quotes([(MARKET_SH, "600000")])

        assert df.empty


# ====================================================================
# get_security_list
# ====================================================================

class TestGetSecurityList:

    def test_returns_dataframe(self, collector, mock_api):
        fake_df = pd.DataFrame({"code": ["600000", "600001"]})
        mock_api.get_security_list.return_value = fake_df

        with patch.object(collector, "_connect_api", return_value=mock_api):
            df = collector.get_security_list(MARKET_SH)

        assert len(df) == 2
        mock_api.get_security_list.assert_called_once_with(MARKET_SH, 0)


# ====================================================================
# get_index_bars
# ====================================================================

class TestGetIndexBars:

    def test_returns_dataframe(self, collector, mock_api):
        fake_df = pd.DataFrame({"open": [3000.0], "close": [3050.0]})
        mock_api.get_index_bars.return_value = fake_df

        with patch.object(collector, "_connect_api", return_value=mock_api):
            df = collector.get_index_bars("000001", MARKET_SH)

        assert len(df) == 1
        mock_api.disconnect.assert_called_once()


# ====================================================================
# collect
# ====================================================================

class TestCollect:

    def test_missing_func_name(self, collector):
        task = CollectTask(params={})
        with pytest.raises(ValueError, match="func_name"):
            collector.collect(task)

    def test_unknown_func_name(self, collector):
        task = CollectTask(params={"func_name": "nonexistent"})
        with pytest.raises(AttributeError, match="没有公开方法"):
            collector.collect(task)

    def test_private_method_blocked(self, collector):
        task = CollectTask(params={"func_name": "_connect_api"})
        with pytest.raises(AttributeError, match="没有公开方法"):
            collector.collect(task)

    def test_successful_collect(self, collector):
        fake_df = pd.DataFrame({"a": [1, 2]})
        with patch.object(collector, "get_security_list", return_value=fake_df):
            task = CollectTask(
                source="pytdx",
                params={"func_name": "get_security_list", "market": 1},
            )
            result = collector.collect(task)

        assert isinstance(result, CollectResult)
        assert result.source == "pytdx"
        assert result.metadata["records_count"] == 2
        assert result.metadata["func_name"] == "get_security_list"
        assert isinstance(result.collected_at, datetime)

    def test_collect_passes_params(self, collector):
        fake_df = pd.DataFrame()
        with patch.object(collector, "get_security_bars", return_value=fake_df) as mock_fn:
            task = CollectTask(params={
                "func_name": "get_security_bars",
                "code": "600000",
                "market": 1,
                "category": 9,
            })
            collector.collect(task)
            mock_fn.assert_called_once_with(code="600000", market=1, category=9)


# ====================================================================
# health_check
# ====================================================================

class TestHealthCheck:

    def test_healthy(self, collector, mock_api):
        with patch.object(collector, "_connect_api", return_value=mock_api):
            assert collector.health_check() is True
            mock_api.disconnect.assert_called_once()

    def test_unhealthy(self, collector):
        with patch.object(collector, "_connect_api", side_effect=RuntimeError("no server")):
            assert collector.health_check() is False
