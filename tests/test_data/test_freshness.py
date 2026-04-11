"""Tests for src/datacollect/freshness.py"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from src.datacollect.freshness import DataFreshnessMonitor, FreshnessAlert


# ====================================================================
# Helpers
# ====================================================================

def _make_monitor_no_calendar() -> DataFreshnessMonitor:
    """创建不依赖 exchange_calendars 的 monitor。"""
    with patch("src.datacollect.freshness.DataFreshnessMonitor.__init__", return_value=None):
        m = DataFreshnessMonitor.__new__(DataFreshnessMonitor)
        m._calendar = None
        m._calendar_name = "XSHG"
    return m


# ====================================================================
# _is_trading_day (fallback)
# ====================================================================

class TestIsTradingDay:

    def test_weekday_is_trading(self):
        m = _make_monitor_no_calendar()
        monday = date(2024, 1, 1)  # Monday
        assert m._is_trading_day(monday) is True

    def test_saturday_not_trading(self):
        m = _make_monitor_no_calendar()
        saturday = date(2024, 1, 6)
        assert m._is_trading_day(saturday) is False

    def test_sunday_not_trading(self):
        m = _make_monitor_no_calendar()
        sunday = date(2024, 1, 7)
        assert m._is_trading_day(sunday) is False


# ====================================================================
# _trading_days_between (fallback)
# ====================================================================

class TestTradingDaysBetween:

    def test_same_date_zero(self):
        m = _make_monitor_no_calendar()
        assert m._trading_days_between(date(2024, 1, 1), date(2024, 1, 1)) == 0

    def test_one_weekday(self):
        m = _make_monitor_no_calendar()
        result = m._trading_days_between(date(2024, 1, 1), date(2024, 1, 2))
        assert result == 1

    def test_across_weekend(self):
        m = _make_monitor_no_calendar()
        friday = date(2024, 1, 5)
        monday = date(2024, 1, 8)
        result = m._trading_days_between(friday, monday)
        assert result == 1

    def test_full_week(self):
        m = _make_monitor_no_calendar()
        result = m._trading_days_between(date(2024, 1, 1), date(2024, 1, 8))
        assert result == 5

    def test_start_after_end_zero(self):
        m = _make_monitor_no_calendar()
        assert m._trading_days_between(date(2024, 1, 10), date(2024, 1, 5)) == 0


# ====================================================================
# _last_trading_day
# ====================================================================

class TestLastTradingDay:

    def test_weekday_returns_same(self):
        m = _make_monitor_no_calendar()
        tuesday = date(2024, 1, 2)
        assert m._last_trading_day(tuesday) == tuesday

    def test_saturday_returns_friday(self):
        m = _make_monitor_no_calendar()
        saturday = date(2024, 1, 6)
        friday = date(2024, 1, 5)
        assert m._last_trading_day(saturday) == friday

    def test_sunday_returns_friday(self):
        m = _make_monitor_no_calendar()
        sunday = date(2024, 1, 7)
        friday = date(2024, 1, 5)
        assert m._last_trading_day(sunday) == friday


# ====================================================================
# check_table
# ====================================================================

class TestCheckTable:

    def test_fresh_data_no_alert(self):
        m = _make_monitor_no_calendar()
        session = MagicMock()

        today = date(2024, 1, 2)  # Tuesday
        session.execute.return_value.scalar.return_value = today

        with patch.object(type(m), "check_table", wraps=m.check_table):
            with patch("src.datacollect.freshness.date", wraps=date) as mock_date:
                mock_date.today.return_value = today
                alert = m.check_table(session, "stock_daily", max_lag=1)

        assert alert is None

    def test_stale_data_returns_alert(self):
        m = _make_monitor_no_calendar()
        session = MagicMock()

        today = date(2024, 1, 10)  # Wednesday
        stale_date = date(2024, 1, 3)
        session.execute.return_value.scalar.return_value = stale_date

        with patch("src.datacollect.freshness.date", wraps=date) as mock_date:
            mock_date.today.return_value = today
            alert = m.check_table(session, "stock_daily", max_lag=1)

        assert alert is not None
        assert isinstance(alert, FreshnessAlert)
        assert alert.table == "stock_daily"
        assert alert.lag_days > 1

    def test_null_date_returns_alert(self):
        m = _make_monitor_no_calendar()
        session = MagicMock()
        session.execute.return_value.scalar.return_value = None

        with patch("src.datacollect.freshness.date", wraps=date) as mock_date:
            mock_date.today.return_value = date(2024, 1, 2)
            alert = m.check_table(session, "stock_daily", max_lag=1)

        assert alert is not None
        assert alert.latest_date is None


# ====================================================================
# check_all
# ====================================================================

class TestCheckAll:

    def test_skips_non_trading_day(self):
        m = _make_monitor_no_calendar()
        session = MagicMock()

        saturday = date(2024, 1, 6)
        with patch("src.datacollect.freshness.date", wraps=date) as mock_date:
            mock_date.today.return_value = saturday
            alerts = m.check_all(session)

        assert alerts == []
        session.execute.assert_not_called()

    def test_returns_alerts_for_stale_tables(self):
        m = _make_monitor_no_calendar()
        session = MagicMock()

        today = date(2024, 1, 10)  # Wednesday
        stale = date(2024, 1, 2)
        session.execute.return_value.scalar.return_value = stale

        with patch("src.datacollect.freshness.date", wraps=date) as mock_date:
            mock_date.today.return_value = today
            alerts = m.check_all(session)

        assert len(alerts) > 0
        tables = {a.table for a in alerts}
        assert "stock_daily" in tables


# ====================================================================
# exchange_calendars integration (mocked)
# ====================================================================

class TestWithExchangeCalendar:

    def test_calendar_init_graceful_fallback(self):
        with patch.dict("sys.modules", {"exchange_calendars": None}):
            m = DataFreshnessMonitor(calendar_name="XSHG")
        assert m._calendar is None

    def test_calendar_used_when_available(self):
        mock_cal = MagicMock()
        mock_ec = MagicMock()
        mock_ec.get_calendar.return_value = mock_cal
        with patch.dict("sys.modules", {"exchange_calendars": mock_ec}):
            m = DataFreshnessMonitor(calendar_name="XSHG")
        assert m._calendar is mock_cal


# ====================================================================
# FreshnessAlert dataclass
# ====================================================================

class TestFreshnessAlert:

    def test_creation(self):
        alert = FreshnessAlert(
            table="stock_daily",
            latest_date=date(2024, 1, 1),
            expected_date=date(2024, 1, 5),
            lag_days=4,
            threshold_days=1,
        )
        assert alert.table == "stock_daily"
        assert alert.lag_days == 4
        assert alert.threshold_days == 1

    def test_none_latest_date(self):
        alert = FreshnessAlert(
            table="market_index",
            latest_date=None,
            expected_date=date(2024, 1, 5),
            lag_days=100,
            threshold_days=1,
        )
        assert alert.latest_date is None
