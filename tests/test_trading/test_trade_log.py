"""Tests for src/trading/trade_log.py - TradeLogger"""
import pytest
from datetime import date
from unittest.mock import patch, MagicMock, PropertyMock

from src.trading.trade_log import TradeLogger


@pytest.fixture
def logger_instance():
    return TradeLogger(account_type="paper")


# ---------------------------------------------------------------------------
# set_initial_assets
# ---------------------------------------------------------------------------

class TestSetInitialAssets:
    def test_sets_value(self, logger_instance):
        logger_instance.set_initial_assets(1_000_000)
        assert logger_instance._initial_assets == 1_000_000

    def test_overwrite(self, logger_instance):
        logger_instance.set_initial_assets(500_000)
        logger_instance.set_initial_assets(800_000)
        assert logger_instance._initial_assets == 800_000

    def test_default_is_none(self):
        tl = TradeLogger()
        assert tl._initial_assets is None


# ---------------------------------------------------------------------------
# log_daily
# ---------------------------------------------------------------------------

class TestLogDaily:
    @patch("src.trading.trade_log.get_session")
    def test_first_day_no_prev(self, mock_get_session, logger_instance):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = None

        logger_instance.log_daily(date(2024, 6, 1), 1_000_000, 500_000, 500_000)

        mock_session.merge.assert_called_once()
        record = mock_session.merge.call_args.args[0]
        assert record.daily_return == 0
        assert record.report_date == date(2024, 6, 1)
        assert record.total_assets == 1_000_000
        assert record.cash == 500_000
        assert record.market_value == 500_000

    @patch("src.trading.trade_log.get_session")
    def test_daily_return_from_prev(self, mock_get_session, logger_instance):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        prev_record = MagicMock()
        prev_record.total_assets = 1_000_000

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = prev_record

        logger_instance.log_daily(date(2024, 6, 2), 1_020_000, 500_000, 520_000)

        record = mock_session.merge.call_args.args[0]
        expected_daily = (1_020_000 - 1_000_000) / 1_000_000 * 100
        assert abs(record.daily_return - expected_daily) < 0.01

    @patch("src.trading.trade_log.get_session")
    def test_cumulative_return_with_initial(self, mock_get_session, logger_instance):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = None

        logger_instance.set_initial_assets(1_000_000)
        logger_instance.log_daily(date(2024, 6, 1), 1_050_000, 500_000, 550_000)

        record = mock_session.merge.call_args.args[0]
        expected_cumul = (1_050_000 - 1_000_000) / 1_000_000 * 100
        assert abs(record.cumulative_return - expected_cumul) < 0.01

    @patch("src.trading.trade_log.get_session")
    def test_cumulative_return_no_initial(self, mock_get_session, logger_instance):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = None

        logger_instance.log_daily(date(2024, 6, 1), 1_050_000, 500_000, 550_000)

        record = mock_session.merge.call_args.args[0]
        assert record.cumulative_return == 0

    @patch("src.trading.trade_log.get_session")
    def test_prev_with_zero_assets(self, mock_get_session, logger_instance):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        prev_record = MagicMock()
        prev_record.total_assets = 0

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = prev_record

        logger_instance.log_daily(date(2024, 6, 2), 100_000, 50_000, 50_000)
        record = mock_session.merge.call_args.args[0]
        assert record.daily_return == 0

    @patch("src.trading.trade_log.get_session")
    def test_account_type_stored(self, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = None

        tl = TradeLogger(account_type="live")
        tl.log_daily(date(2024, 6, 1), 500_000, 300_000, 200_000)

        record = mock_session.merge.call_args.args[0]
        assert record.account_type == "live"

    @patch("src.trading.trade_log.get_session")
    def test_negative_daily_return(self, mock_get_session, logger_instance):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        prev_record = MagicMock()
        prev_record.total_assets = 1_000_000

        mock_query = MagicMock()
        mock_session.query.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value = mock_query
        mock_query.first.return_value = prev_record

        logger_instance.log_daily(date(2024, 6, 2), 950_000, 450_000, 500_000)

        record = mock_session.merge.call_args.args[0]
        expected = (950_000 - 1_000_000) / 1_000_000 * 100
        assert abs(record.daily_return - expected) < 0.01
        assert record.daily_return < 0
