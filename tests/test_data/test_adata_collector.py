"""Tests for src/datacollect/collectors/adata_collector.py — CB methods"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.datacollect.collectors.adata_collector import AdataCollector


@pytest.fixture
def mock_limiter():
    limiter = MagicMock()
    limiter.acquire.return_value = True
    return limiter


@pytest.fixture
def collector(mock_limiter):
    return AdataCollector(limiter=mock_limiter)


class TestGetCbList:

    def test_calls_bond_info(self, collector):
        with patch.object(collector, "call_adata", return_value=MagicMock()) as mock_call:
            collector.get_cb_list()
            mock_call.assert_called_once_with("bond.info", "all_code")


class TestGetCbMarket:

    def test_calls_bond_market(self, collector):
        with patch.object(collector, "call_adata", return_value=MagicMock()) as mock_call:
            collector.get_cb_market("123456", start_date="2023-01-01")
            mock_call.assert_called_once_with(
                "bond.market", "get_market",
                stock_code="123456", start_date="2023-01-01",
            )
