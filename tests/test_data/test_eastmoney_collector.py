"""Tests for src/datacollect/collectors/eastmoney_collector.py"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.datacollect.base import CollectResult, CollectTask
from src.datacollect.collectors.eastmoney_collector import EastmoneyCollector


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture
def mock_limiter():
    limiter = MagicMock()
    limiter.acquire.return_value = True
    return limiter


@pytest.fixture
def mock_client():
    return MagicMock()


@pytest.fixture
def collector(mock_limiter, mock_client):
    return EastmoneyCollector(limiter=mock_limiter, client=mock_client)


def _make_response(json_data: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = json_data
    return resp


# ====================================================================
# __init__ / SOURCE
# ====================================================================

class TestInit:

    def test_custom_limiter_and_client(self, mock_limiter, mock_client):
        c = EastmoneyCollector(limiter=mock_limiter, client=mock_client)
        assert c.limiter is mock_limiter
        assert c._client is mock_client

    @patch("src.datacollect.collectors.eastmoney_collector.TokenBucketLimiter")
    @patch("src.datacollect.collectors.eastmoney_collector.SmartHttpClient")
    def test_default_limiter_and_client(self, mock_http, mock_tbl):
        mock_tbl.for_domain.return_value = MagicMock()
        c = EastmoneyCollector()
        mock_tbl.for_domain.assert_called_once()
        assert c.limiter is mock_tbl.for_domain.return_value

    def test_source_name(self, collector):
        assert collector.SOURCE == "eastmoney"


# ====================================================================
# _secid
# ====================================================================

class TestSecid:

    def test_sh_stock(self):
        assert EastmoneyCollector._secid("600000") == "1.600000"

    def test_sh_688(self):
        assert EastmoneyCollector._secid("688001") == "1.688001"

    def test_sz_stock(self):
        assert EastmoneyCollector._secid("000001") == "0.000001"

    def test_sz_300(self):
        assert EastmoneyCollector._secid("300001") == "0.300001"

    def test_sz_002(self):
        assert EastmoneyCollector._secid("002001") == "0.002001"


# ====================================================================
# _request
# ====================================================================

class TestRequest:

    def test_successful_request(self, collector, mock_client, mock_limiter):
        mock_client.get.return_value = _make_response({"rc": 0, "data": {}})
        result = collector._request("http://test.com", {"a": "1"})
        assert result == {"rc": 0, "data": {}}
        mock_limiter.acquire.assert_called_once()

    def test_request_without_limiter(self, mock_client):
        c = EastmoneyCollector(limiter=None, client=mock_client)
        mock_client.get.return_value = _make_response({"rc": 0, "data": {}})
        result = c._request("http://test.com", {})
        assert result["rc"] == 0

    def test_api_error(self, collector, mock_client):
        mock_client.get.return_value = _make_response({"rc": -1, "msg": "bad"})
        with pytest.raises(RuntimeError, match="东财 API 错误"):
            collector._request("http://test.com", {})

    def test_rc_none_no_error(self, collector, mock_client):
        """rc=None (e.g. some endpoints) should not raise."""
        mock_client.get.return_value = _make_response({"data": {"diff": []}})
        result = collector._request("http://test.com", {})
        assert "data" in result


# ====================================================================
# fetch_stock_list
# ====================================================================

class TestFetchStockList:

    def test_parses_diff(self, collector, mock_client):
        mock_client.get.return_value = _make_response({
            "rc": 0,
            "data": {
                "diff": [
                    {"f12": "000001", "f14": "平安银行", "f2": 12.5, "f3": 1.2, "f5": 100000, "f6": 1250000},
                    {"f12": "600000", "f14": "浦发银行", "f2": 8.3, "f3": -0.5, "f5": 80000, "f6": 664000},
                ],
            },
        })
        df = collector.fetch_stock_list()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert list(df.columns) == ["code", "name", "price", "change_pct", "volume", "amount"]
        assert df.iloc[0]["code"] == "000001"
        assert df.iloc[1]["name"] == "浦发银行"

    def test_empty_diff(self, collector, mock_client):
        mock_client.get.return_value = _make_response({"rc": 0, "data": {"diff": []}})
        df = collector.fetch_stock_list()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0

    def test_missing_data_key(self, collector, mock_client):
        mock_client.get.return_value = _make_response({"rc": 0, "data": {}})
        df = collector.fetch_stock_list()
        assert len(df) == 0


# ====================================================================
# fetch_kline
# ====================================================================

class TestFetchKline:

    def test_parses_klines(self, collector, mock_client):
        mock_client.get.return_value = _make_response({
            "rc": 0,
            "data": {
                "klines": [
                    "2023-01-03,13.20,13.46,13.48,13.11,574529,771046656.00,2.82,1.89,0.25,4.35",
                    "2023-01-04,13.50,13.60,13.70,13.40,400000,540000000.00,2.22,1.04,0.14,3.10",
                ],
            },
        })
        df = collector.fetch_kline("000001", "20230101", "20230105")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert "code" in df.columns
        assert df.iloc[0]["code"] == "000001"
        assert df.iloc[0]["date"] == "2023-01-03"
        assert df.iloc[0]["open"] == 13.20
        assert df.iloc[0]["close"] == 13.46

    def test_empty_klines(self, collector, mock_client):
        mock_client.get.return_value = _make_response({"rc": 0, "data": {"klines": []}})
        df = collector.fetch_kline("000001")
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0
        assert "code" in df.columns

    def test_secid_in_params(self, collector, mock_client):
        mock_client.get.return_value = _make_response({"rc": 0, "data": {"klines": []}})
        collector.fetch_kline("600000")
        call_params = mock_client.get.call_args
        assert call_params[1]["params"]["secid"] == "1.600000"

    def test_malformed_kline_skipped(self, collector, mock_client):
        mock_client.get.return_value = _make_response({
            "rc": 0,
            "data": {
                "klines": [
                    "2023-01-03,13.20",
                    "2023-01-04,13.50,13.60,13.70,13.40,400000,540000000.00,2.22,1.04,0.14,3.10",
                ],
            },
        })
        df = collector.fetch_kline("000001")
        assert len(df) == 1


# ====================================================================
# fetch_realtime
# ====================================================================

class TestFetchRealtime:

    def test_parses_realtime(self, collector, mock_client):
        mock_client.get.return_value = _make_response({
            "rc": 0,
            "data": {
                "diff": [
                    {"f12": "000001", "f14": "平安银行", "f2": 12.5, "f3": 1.2, "f5": 100000, "f6": 1250000},
                ],
            },
        })
        df = collector.fetch_realtime()
        assert len(df) == 1
        assert df.iloc[0]["code"] == "000001"


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
        with pytest.raises(AttributeError, match="没有方法"):
            collector.collect(task)

    def test_successful_collect(self, collector):
        fake_df = pd.DataFrame({"code": ["000001"], "name": ["平安银行"]})
        with patch.object(collector, "fetch_stock_list", return_value=fake_df):
            task = CollectTask(
                source="eastmoney",
                params={"func_name": "fetch_stock_list"},
            )
            result = collector.collect(task)

        assert isinstance(result, CollectResult)
        assert result.source == "eastmoney"
        assert result.metadata["records_count"] == 1
        assert result.metadata["func_name"] == "fetch_stock_list"
        assert isinstance(result.collected_at, datetime)

    def test_collect_passes_kline_params(self, collector):
        fake_df = pd.DataFrame()
        with patch.object(collector, "fetch_kline", return_value=fake_df) as mock_fn:
            task = CollectTask(params={
                "func_name": "fetch_kline",
                "code": "000001",
                "start_date": "20230101",
                "end_date": "20231231",
            })
            collector.collect(task)
            mock_fn.assert_called_once_with(
                code="000001",
                start_date="20230101",
                end_date="20231231",
            )


# ====================================================================
# health_check
# ====================================================================

class TestHealthCheck:

    def test_healthy(self, collector):
        fake_df = pd.DataFrame({"code": ["000001"]})
        with patch.object(collector, "fetch_stock_list", return_value=fake_df):
            assert collector.health_check() is True

    def test_empty_result(self, collector):
        with patch.object(collector, "fetch_stock_list", return_value=pd.DataFrame()):
            assert collector.health_check() is False

    def test_exception(self, collector):
        with patch.object(collector, "fetch_stock_list", side_effect=RuntimeError("fail")):
            assert collector.health_check() is False


# ====================================================================
# func_for_data_type
# ====================================================================

class TestFuncForDataType:

    def test_known_types(self):
        assert EastmoneyCollector.func_for_data_type("stock_list") == "fetch_stock_list"
        assert EastmoneyCollector.func_for_data_type("daily_kline") == "fetch_kline"
        assert EastmoneyCollector.func_for_data_type("realtime") == "fetch_realtime"

    def test_unknown_type(self):
        assert EastmoneyCollector.func_for_data_type("cb") is None
