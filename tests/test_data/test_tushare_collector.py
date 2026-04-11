"""Tests for src/datacollect/collectors/tushare_collector.py — CB methods"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.datacollect.collectors.tushare_collector import TushareCollector


@pytest.fixture
def mock_limiter():
    limiter = MagicMock()
    limiter.acquire.return_value = True
    return limiter


@pytest.fixture
def collector(mock_limiter):
    c = TushareCollector(limiter=mock_limiter)
    c._token = "test_token"
    return c


class TestQueryCbBasic:

    def test_calls_cb_basic(self, collector):
        with patch.object(collector, "query", return_value=MagicMock()) as mock_q:
            collector.query_cb_basic(exchange="SSE")
            mock_q.assert_called_once_with("cb_basic", exchange="SSE")


class TestQueryCbDaily:

    def test_calls_cb_daily(self, collector):
        with patch.object(collector, "query", return_value=MagicMock()) as mock_q:
            collector.query_cb_daily(ts_code="123456.SZ", start_date="20230101")
            mock_q.assert_called_once_with(
                "cb_daily", ts_code="123456.SZ", start_date="20230101",
            )

    def test_empty_params_excluded(self, collector):
        with patch.object(collector, "query", return_value=MagicMock()) as mock_q:
            collector.query_cb_daily()
            mock_q.assert_called_once_with("cb_daily")
