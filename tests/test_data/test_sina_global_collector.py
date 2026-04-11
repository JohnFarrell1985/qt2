"""Tests for SinaGlobalCollector"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.datacollect.base import CollectTask
from src.datacollect.collectors.sina_global_collector import (
    SinaGlobalCollector, SINA_SYMBOL_MAP,
)


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
    return SinaGlobalCollector(limiter=mock_limiter, client=mock_client)


class TestFetchQuotes:
    def test_parses_sina_response(self, collector, mock_client):
        raw_text = (
            'var hq_str_int_dji="道琼斯,40000.12,40100.50,39900.00,40000.12,100000,0,39500.00,0,0";\n'
            'var hq_str_int_nasdaq="纳斯达克,17000.50,17100.00,16900.00,17000.50,200000,0,16800.00,0,0";\n'
        )
        resp = MagicMock()
        resp.text = raw_text
        mock_client.get.return_value = resp

        rows = collector._fetch_quotes(SINA_SYMBOL_MAP["global_index"])
        assert len(rows) >= 2
        symbols = [r["symbol"] for r in rows]
        assert "DJI" in symbols
        assert "NASDAQ" in symbols
        for row in rows:
            assert "close_price" in row
            assert "trade_date" in row

    def test_empty_response(self, collector, mock_client):
        resp = MagicMock()
        resp.text = ""
        mock_client.get.return_value = resp
        rows = collector._fetch_quotes({"TEST": "int_test"})
        assert rows == []

    def test_malformed_response(self, collector, mock_client):
        resp = MagicMock()
        resp.text = 'var hq_str_int_test="";'
        mock_client.get.return_value = resp
        rows = collector._fetch_quotes({"TEST": "int_test"})
        assert rows == []

    def test_request_failure(self, collector, mock_client):
        mock_client.get.side_effect = ConnectionError("network error")
        rows = collector._fetch_quotes({"TEST": "int_test"})
        assert rows == []


class TestCollect:
    def test_collect_via_data_type(self, collector):
        with patch.object(collector, "fetch_forex", return_value=[{"symbol": "USDCNY"}]):
            task = CollectTask(data_type="forex", params={})
            result = collector.collect(task)
            assert result.source == "sina_global"
            assert result.metadata["records_count"] == 1

    def test_missing_method(self, collector):
        task = CollectTask(data_type="nonexistent", params={})
        with pytest.raises(ValueError):
            collector.collect(task)


class TestHealthCheck:
    def test_healthy(self, collector):
        with patch.object(collector, "fetch_global_index", return_value=[{"s": "DJI"}]):
            assert collector.health_check() is True

    def test_empty(self, collector):
        with patch.object(collector, "fetch_global_index", return_value=[]):
            assert collector.health_check() is False


class TestFuncForDataType:
    def test_known(self):
        assert SinaGlobalCollector.func_for_data_type("forex") == "fetch_forex"

    def test_unknown(self):
        assert SinaGlobalCollector.func_for_data_type("bond_yield") is None
