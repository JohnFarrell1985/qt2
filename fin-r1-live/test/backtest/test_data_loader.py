"""
data_loader.py 单元测试 — 直接 mock SessionLocal 验证数据访问逻辑
"""
from datetime import date
from unittest.mock import patch, MagicMock

import pytest

from backtest import data_loader


# ======== Mock helpers ========

def _mock_row(**kwargs):
    """创建模拟数据库行"""
    row = MagicMock()
    for k, v in kwargs.items():
        setattr(row, k, v)
    return row


def _mock_session_with_rows(rows):
    """创建返回指定行的 mock session"""
    session = MagicMock()
    result = MagicMock()
    result.fetchone.return_value = rows[0] if rows else None
    result.fetchall.return_value = rows
    session.execute.return_value = result
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


# ======== get_close_price ========

class TestGetClosePrice:
    @patch.object(data_loader, 'SessionLocal')
    def test_exact_date_match(self, mock_sl):
        row = _mock_row(close=10.2, trade_date=date(2025, 1, 2))
        mock_sl.return_value = _mock_session_with_rows([row])
        price = data_loader.get_close_price("000001", date(2025, 1, 2))
        assert price == 10.2

    @patch.object(data_loader, 'SessionLocal')
    def test_returns_none_when_no_data(self, mock_sl):
        mock_sl.return_value = _mock_session_with_rows([])
        price = data_loader.get_close_price("999999", date(2025, 1, 2))
        assert price is None

    @patch.object(data_loader, 'SessionLocal')
    def test_returns_float(self, mock_sl):
        row = _mock_row(close=10, trade_date=date(2025, 1, 2))
        mock_sl.return_value = _mock_session_with_rows([row])
        price = data_loader.get_close_price("000001", date(2025, 1, 2))
        assert isinstance(price, float)


# ======== get_daily_data ========

class TestGetDailyData:
    @patch.object(data_loader, 'SessionLocal')
    def test_returns_list_of_dicts(self, mock_sl):
        rows = [
            _mock_row(code="000001", trade_date=date(2025, 1, 2), open=10.0, high=10.5,
                       low=9.8, close=10.2, volume=500000, amount=5100000.0,
                       change_pct=1.0, turnover_rate=0.5, pre_close=10.1),
        ]
        mock_sl.return_value = _mock_session_with_rows(rows)
        data = data_loader.get_daily_data("000001", date(2025, 1, 2), date(2025, 1, 2))
        assert len(data) == 1
        d = data[0]
        assert d["code"] == "000001"
        assert d["close"] == 10.2
        assert d["open"] == 10.0
        assert d["high"] == 10.5
        assert d["low"] == 9.8
        assert d["volume"] == 500000
        assert d["amount"] == 5100000.0
        assert d["change_pct"] == 1.0
        assert d["pre_close"] == 10.1

    @patch.object(data_loader, 'SessionLocal')
    def test_empty_result(self, mock_sl):
        mock_sl.return_value = _mock_session_with_rows([])
        data = data_loader.get_daily_data("999999", date(2025, 1, 1), date(2025, 12, 31))
        assert data == []

    @patch.object(data_loader, 'SessionLocal')
    def test_handles_none_fields(self, mock_sl):
        row = _mock_row(code="000001", trade_date=date(2025, 1, 2), open=None,
                         high=None, low=None, close=None, volume=None, amount=None,
                         change_pct=None, turnover_rate=None, pre_close=None)
        mock_sl.return_value = _mock_session_with_rows([row])
        data = data_loader.get_daily_data("000001", date(2025, 1, 2), date(2025, 1, 2))
        d = data[0]
        assert d["open"] is None
        assert d["close"] is None
        assert d["volume"] == 0
        assert d["amount"] == 0
        assert d["change_pct"] == 0
        assert d["pre_close"] is None

    @patch.object(data_loader, 'SessionLocal')
    def test_multiple_rows(self, mock_sl):
        rows = [
            _mock_row(code="000001", trade_date=date(2025, 1, 2), open=10.0, high=10.5,
                       low=9.8, close=10.2, volume=500000, amount=5100000.0,
                       change_pct=1.0, turnover_rate=0.5, pre_close=10.1),
            _mock_row(code="000001", trade_date=date(2025, 1, 3), open=10.2, high=10.8,
                       low=10.0, close=10.5, volume=600000, amount=6300000.0,
                       change_pct=2.94, turnover_rate=0.6, pre_close=10.2),
        ]
        mock_sl.return_value = _mock_session_with_rows(rows)
        data = data_loader.get_daily_data("000001", date(2025, 1, 2), date(2025, 1, 3))
        assert len(data) == 2


# ======== get_stock_name ========

class TestGetStockName:
    @patch.object(data_loader, 'SessionLocal')
    def test_known_stock(self, mock_sl):
        row = _mock_row(name="平安银行")
        mock_sl.return_value = _mock_session_with_rows([row])
        assert data_loader.get_stock_name("000001") == "平安银行"

    @patch.object(data_loader, 'SessionLocal')
    def test_unknown_stock(self, mock_sl):
        mock_sl.return_value = _mock_session_with_rows([])
        assert data_loader.get_stock_name("999999") is None


# ======== get_data_range ========

class TestGetDataRange:
    @patch.object(data_loader, 'SessionLocal')
    def test_known_stock(self, mock_sl):
        row = _mock_row(min_date=date(2024, 1, 2), max_date=date(2025, 12, 31), total_days=480)
        mock_sl.return_value = _mock_session_with_rows([row])
        r = data_loader.get_data_range("000001")
        assert r is not None
        assert r["min_date"] == date(2024, 1, 2)
        assert r["max_date"] == date(2025, 12, 31)
        assert r["total_days"] == 480

    @patch.object(data_loader, 'SessionLocal')
    def test_unknown_stock_returns_none(self, mock_sl):
        row = _mock_row(min_date=None, max_date=None, total_days=0)
        mock_sl.return_value = _mock_session_with_rows([row])
        assert data_loader.get_data_range("999999") is None

    @patch.object(data_loader, 'SessionLocal')
    def test_no_row_returns_none(self, mock_sl):
        mock_sl.return_value = _mock_session_with_rows([])
        assert data_loader.get_data_range("999999") is None


# ======== get_open_price ========

class TestGetOpenPrice:
    @patch.object(data_loader, 'SessionLocal')
    def test_exact_date(self, mock_sl):
        row = _mock_row(open=10.5, trade_date=date(2025, 1, 6))
        mock_sl.return_value = _mock_session_with_rows([row])
        price = data_loader.get_open_price("000001", date(2025, 1, 6))
        assert price == 10.5

    @patch.object(data_loader, 'SessionLocal')
    def test_returns_none(self, mock_sl):
        mock_sl.return_value = _mock_session_with_rows([])
        assert data_loader.get_open_price("999999", date(2025, 1, 1)) is None

    @patch.object(data_loader, 'SessionLocal')
    def test_returns_float(self, mock_sl):
        row = _mock_row(open=10, trade_date=date(2025, 1, 6))
        mock_sl.return_value = _mock_session_with_rows([row])
        price = data_loader.get_open_price("000001", date(2025, 1, 6))
        assert isinstance(price, float)


# ======== get_open_price_exact ========

class TestGetOpenPriceExact:
    @patch.object(data_loader, 'SessionLocal')
    def test_trading_day(self, mock_sl):
        row = _mock_row(open=10.5, close=10.8, pre_close=10.2, high=11.0,
                         low=10.3, change_pct=2.86, trade_date=date(2025, 1, 6))
        mock_sl.return_value = _mock_session_with_rows([row])
        data = data_loader.get_open_price_exact("000001", date(2025, 1, 6))
        assert data is not None
        assert data["open"] == 10.5
        assert data["close"] == 10.8
        assert data["pre_close"] == 10.2

    @patch.object(data_loader, 'SessionLocal')
    def test_non_trading_day(self, mock_sl):
        mock_sl.return_value = _mock_session_with_rows([])
        data = data_loader.get_open_price_exact("000001", date(2025, 1, 4))
        assert data is None

    @patch.object(data_loader, 'SessionLocal')
    def test_none_fields(self, mock_sl):
        row = _mock_row(open=None, close=None, pre_close=None, high=None,
                         low=None, change_pct=None, trade_date=date(2025, 1, 6))
        mock_sl.return_value = _mock_session_with_rows([row])
        data = data_loader.get_open_price_exact("000001", date(2025, 1, 6))
        assert data["open"] is None
        assert data["change_pct"] is None


# ======== get_trading_dates ========

class TestGetTradingDates:
    @patch.object(data_loader, 'SessionLocal')
    def test_returns_dates(self, mock_sl):
        rows = [
            _mock_row(trade_date=date(2025, 1, 2)),
            _mock_row(trade_date=date(2025, 1, 3)),
            _mock_row(trade_date=date(2025, 1, 6)),
        ]
        mock_sl.return_value = _mock_session_with_rows(rows)
        dates = data_loader.get_trading_dates(date(2025, 1, 1), date(2025, 1, 10))
        assert len(dates) == 3
        assert dates[0] == date(2025, 1, 2)

    @patch.object(data_loader, 'SessionLocal')
    def test_empty(self, mock_sl):
        mock_sl.return_value = _mock_session_with_rows([])
        dates = data_loader.get_trading_dates(date(2020, 1, 1), date(2020, 1, 5))
        assert dates == []


# ======== get_next_trading_date ========

class TestGetNextTradingDate:
    @patch.object(data_loader, 'SessionLocal')
    def test_found(self, mock_sl):
        row = _mock_row(trade_date=date(2025, 1, 3))
        mock_sl.return_value = _mock_session_with_rows([row])
        d = data_loader.get_next_trading_date(date(2025, 1, 2))
        assert d == date(2025, 1, 3)

    @patch.object(data_loader, 'SessionLocal')
    def test_not_found(self, mock_sl):
        mock_sl.return_value = _mock_session_with_rows([])
        d = data_loader.get_next_trading_date(date(2099, 12, 31))
        assert d is None
