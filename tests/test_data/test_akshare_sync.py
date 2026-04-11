"""Tests for src/data/akshare_sync.py"""
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.data.akshare_sync import (
    AkshareDataSync,
    _bulk_upsert_daily,
    _bulk_upsert_index,
    _exchange_from_code,
    _safe_float,
    _safe_int,
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
def mock_ak():
    """Mock the akshare module for lazy imports inside method bodies."""
    mock = MagicMock()
    with patch.dict("sys.modules", {"akshare": mock}):
        yield mock


@pytest.fixture
def syncer(mock_limiter, mock_ak):
    with patch.object(AkshareDataSync, "__init__", lambda self: None):
        s = AkshareDataSync()
        s.limiter = mock_limiter
        return s


# ====================================================================
# _exchange_from_code
# ====================================================================

class TestExchangeFromCode:

    def test_sh(self):
        assert _exchange_from_code("600000") == "SH"
        assert _exchange_from_code("688001") == "SH"

    def test_sz(self):
        assert _exchange_from_code("000001") == "SZ"
        assert _exchange_from_code("300001") == "SZ"

    def test_bj(self):
        assert _exchange_from_code("430047") == "BJ"
        assert _exchange_from_code("830799") == "BJ"

    def test_unknown(self):
        assert _exchange_from_code("999999") == ""


# ====================================================================
# A09: sync_stock_list
# ====================================================================

class TestSyncStockList:

    @patch("src.data.akshare_sync.get_session")
    def test_basic_sync(self, mock_get_session, syncer, mock_ak):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        df = pd.DataFrame({
            "code": ["600000", "000001", "300001"],
            "name": ["浦发银行", "平安银行", "特锐德"],
        })
        mock_ak.stock_info_a_code_name.return_value = df

        count = syncer.sync_stock_list()

        assert count == 3
        assert mock_session.execute.called

    @patch("src.data.akshare_sync.get_session")
    def test_empty_df_returns_zero(self, mock_get_session, syncer, mock_ak):
        mock_ak.stock_info_a_code_name.return_value = pd.DataFrame()
        count = syncer.sync_stock_list()
        assert count == 0

    @patch("src.data.akshare_sync.get_session")
    def test_filters_invalid_codes(self, mock_get_session, syncer, mock_ak):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        df = pd.DataFrame({
            "code": ["600000", "12", "", "000001"],
            "name": ["浦发银行", "短码", "空", "平安银行"],
        })
        mock_ak.stock_info_a_code_name.return_value = df

        count = syncer.sync_stock_list()
        assert count == 2


# ====================================================================
# A10: sync_daily_incremental
# ====================================================================

class TestSyncDailyIncremental:

    @patch("src.data.akshare_sync.get_session")
    def test_empty_stocks_table(self, mock_get_session, syncer):
        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = []
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        count = syncer.sync_daily_incremental(days_back=7)
        assert count == 0

    def test_fetch_daily_for_stock(self, syncer, mock_ak):
        df = pd.DataFrame({
            "日期": [datetime(2024, 1, 2), datetime(2024, 1, 3)],
            "开盘": [10.0, 10.5],
            "最高": [10.5, 11.0],
            "最低": [9.5, 10.0],
            "收盘": [10.2, 10.8],
            "成交量": [100000, 120000],
            "成交额": [1020000.0, 1296000.0],
            "振幅": [10.0, 9.5],
            "涨跌幅": [2.0, 5.88],
            "涨跌额": [0.2, 0.6],
            "换手率": [1.5, 1.8],
        })
        mock_ak.stock_zh_a_hist.return_value = df

        records = syncer._fetch_daily_for_stock("600000", "20240101", "20240103")

        assert len(records) == 2
        assert records[0]["code"] == "600000"
        assert records[0]["trade_date"] == date(2024, 1, 2)
        assert records[0]["open"] == 10.0
        assert records[0]["close"] == 10.2
        assert records[0]["volume"] == 100000
        assert records[0]["turnover_rate"] == 1.5

    def test_fetch_daily_empty_df(self, syncer, mock_ak):
        mock_ak.stock_zh_a_hist.return_value = pd.DataFrame()
        records = syncer._fetch_daily_for_stock("600000", "20240101", "20240103")
        assert records == []

    def test_fetch_daily_string_dates(self, syncer, mock_ak):
        """akshare 有时返回字符串日期而非 datetime 对象"""
        df = pd.DataFrame({
            "日期": ["2024-01-02"],
            "开盘": [10.0], "最高": [10.5], "最低": [9.5], "收盘": [10.2],
            "成交量": [100000], "成交额": [1020000.0],
            "振幅": [10.0], "涨跌幅": [2.0], "涨跌额": [0.2], "换手率": [1.5],
        })
        mock_ak.stock_zh_a_hist.return_value = df

        records = syncer._fetch_daily_for_stock("600000", "20240101", "20240103")
        assert len(records) == 1
        assert records[0]["trade_date"] == date(2024, 1, 2)


# ====================================================================
# A11: sync_index_data
# ====================================================================

class TestSyncIndexData:

    @patch("src.data.akshare_sync.get_session")
    def test_basic_index_sync(self, mock_get_session, syncer, mock_ak):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        df = pd.DataFrame({
            "日期": [datetime(2024, 1, 2), datetime(2024, 1, 3)],
            "开盘": [3000.0, 3010.0],
            "最高": [3050.0, 3060.0],
            "最低": [2990.0, 3000.0],
            "收盘": [3020.0, 3040.0],
            "成交量": [30000000, 32000000],
            "成交额": [400000000.0, 420000000.0],
        })
        mock_ak.stock_zh_index_daily_em.return_value = df

        count = syncer.sync_index_data(start_date="20240101")

        assert count > 0
        assert mock_session.execute.called

    @patch("src.data.akshare_sync.get_session")
    def test_handles_api_failure_gracefully(self, mock_get_session, syncer, mock_ak):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_ak.stock_zh_index_daily_em.side_effect = Exception("API error")
        count = syncer.sync_index_data(start_date="20240101")
        assert count == 0

    def test_parse_index_df_calculates_change(self, syncer):
        df = pd.DataFrame({
            "日期": [datetime(2024, 1, 2), datetime(2024, 1, 3)],
            "开盘": [3000.0, 3020.0],
            "最高": [3050.0, 3060.0],
            "最低": [2990.0, 3000.0],
            "收盘": [3020.0, 3040.0],
            "成交量": [30000000, 32000000],
            "成交额": [400000000.0, 420000000.0],
        })

        records = syncer._parse_index_df("000001", "上证综指", df)

        assert len(records) == 2
        assert records[0]["index_code"] == "000001"
        assert records[0]["index_name"] == "上证综指"
        assert records[0]["change"] is None
        assert records[1]["change"] == 20.0
        assert records[1]["change_pct"] == pytest.approx(0.6623, abs=0.001)

    def test_parse_index_df_preserves_existing_change(self, syncer):
        """如果 akshare 返回了 涨跌额/涨跌幅, 应优先使用"""
        df = pd.DataFrame({
            "日期": [datetime(2024, 1, 2)],
            "开盘": [3000.0], "最高": [3050.0], "最低": [2990.0],
            "收盘": [3020.0], "成交量": [30000000], "成交额": [400000000.0],
            "涨跌额": [15.5], "涨跌幅": [0.52],
        })

        records = syncer._parse_index_df("000001", "上证综指", df)
        assert records[0]["change"] == 15.5
        assert records[0]["change_pct"] == 0.52


# ====================================================================
# 工具函数
# ====================================================================

class TestSafeFloat:

    def test_valid_value(self):
        row = pd.Series({"price": 10.5})
        assert _safe_float(row, "price") == 10.5

    def test_nan_returns_none(self):
        row = pd.Series({"price": float("nan")})
        assert _safe_float(row, "price") is None

    def test_missing_col_returns_none(self):
        row = pd.Series({"other": 1.0})
        assert _safe_float(row, "price") is None


class TestSafeInt:

    def test_valid_value(self):
        row = pd.Series({"volume": 100000})
        assert _safe_int(row, "volume") == 100000

    def test_nan_returns_none(self):
        row = pd.Series({"volume": float("nan")})
        assert _safe_int(row, "volume") is None


# ====================================================================
# bulk upsert 函数
# ====================================================================

class TestBulkUpsertDaily:

    def test_executes_insert_statement(self):
        session = MagicMock()
        records = [
            {
                "code": "600000", "trade_date": date(2024, 1, 2),
                "open": 10.0, "high": 10.5, "low": 9.5, "close": 10.2,
                "volume": 100000, "amount": 1020000.0,
                "amplitude": 10.0, "change_pct": 2.0, "change": 0.2,
                "turnover_rate": 1.5,
            },
        ]
        count = _bulk_upsert_daily(session, records)
        assert count == 1
        session.execute.assert_called_once()


class TestBulkUpsertIndex:

    def test_executes_insert_statement(self):
        session = MagicMock()
        records = [
            {
                "index_code": "000001", "index_name": "上证综指",
                "trade_date": date(2024, 1, 2),
                "open": 3000.0, "high": 3050.0, "low": 2990.0,
                "close": 3020.0, "volume": 30000000,
                "amount": 400000000.0, "change": 20.0, "change_pct": 0.67,
            },
        ]
        count = _bulk_upsert_index(session, records)
        assert count == 1
        session.execute.assert_called_once()

    def test_batches_large_input(self):
        session = MagicMock()
        records = [
            {
                "index_code": "000001", "index_name": "上证综指",
                "trade_date": date(2024, 1, i % 28 + 1),
                "open": 3000.0, "high": 3050.0, "low": 2990.0,
                "close": 3020.0, "volume": 30000000,
                "amount": 400000000.0, "change": 20.0, "change_pct": 0.67,
            }
            for i in range(2500)
        ]
        count = _bulk_upsert_index(session, records, batch_size=1000)
        assert count == 2500
        assert session.execute.call_count == 3
