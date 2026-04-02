"""Tests for src/trading/risk_control.py - RiskController"""
import pytest
from unittest.mock import patch, MagicMock

from src.trading.risk_control import RiskController


@pytest.fixture
def rc():
    return RiskController(
        stop_loss_pct=-8.0,
        take_profit_pct=20.0,
        max_single_position_pct=30.0,
        max_total_position_pct=80.0,
        max_daily_loss_pct=-5.0,
    )


# ---------------------------------------------------------------------------
# from_config
# ---------------------------------------------------------------------------

class TestFromConfig:
    @patch("src.trading.risk_control.settings")
    def test_from_config(self, mock_settings):
        mock_risk = MagicMock()
        mock_risk.stop_loss_pct = -10.0
        mock_risk.take_profit_pct = 25.0
        mock_risk.max_single_position_pct = 20.0
        mock_risk.max_total_position_pct = 70.0
        mock_risk.max_daily_loss_pct = -3.0
        mock_settings.trading.risk = mock_risk

        rc = RiskController.from_config()
        assert rc.stop_loss_pct == -10.0
        assert rc.take_profit_pct == 25.0
        assert rc.max_single_position_pct == 20.0
        assert rc.max_total_position_pct == 70.0
        assert rc.max_daily_loss_pct == -3.0


# ---------------------------------------------------------------------------
# check_position_limit
# ---------------------------------------------------------------------------

class TestCheckPositionLimit:
    def test_within_limit(self, rc):
        assert rc.check_position_limit("000001", 20_000, 100_000) is True

    def test_exactly_at_limit(self, rc):
        assert rc.check_position_limit("000001", 30_000, 100_000) is True

    def test_exceeds_limit(self, rc):
        assert rc.check_position_limit("000001", 35_000, 100_000) is False

    def test_zero_total_assets(self, rc):
        assert rc.check_position_limit("000001", 1_000, 0) is False

    def test_small_buy(self, rc):
        assert rc.check_position_limit("000001", 100, 1_000_000) is True


# ---------------------------------------------------------------------------
# check_total_position
# ---------------------------------------------------------------------------

class TestCheckTotalPosition:
    def test_within_limit(self, rc):
        assert rc.check_total_position(70_000, 100_000) is True

    def test_at_limit(self, rc):
        assert rc.check_total_position(80_000, 100_000) is True

    def test_exceeds_limit(self, rc):
        assert rc.check_total_position(85_000, 100_000) is False

    def test_zero_total_assets(self, rc):
        assert rc.check_total_position(1_000, 0) is False


# ---------------------------------------------------------------------------
# check_stop_loss
# ---------------------------------------------------------------------------

class TestCheckStopLoss:
    def test_no_stop_normal(self, rc):
        assert rc.check_stop_loss("000001", 10.0, 10.0) is False

    def test_triggers_stop(self, rc):
        assert rc.check_stop_loss("000001", 9.0, 10.0) is True

    def test_exactly_at_threshold(self, rc):
        cost = 100.0
        price = cost * (1 + rc.stop_loss_pct / 100)
        assert rc.check_stop_loss("000001", price, cost) is True

    def test_zero_cost_price(self, rc):
        assert rc.check_stop_loss("000001", 5.0, 0) is False

    def test_negative_cost_price(self, rc):
        assert rc.check_stop_loss("000001", 5.0, -1.0) is False

    def test_small_loss_no_stop(self, rc):
        assert rc.check_stop_loss("000001", 9.5, 10.0) is False

    def test_profit_no_stop(self, rc):
        assert rc.check_stop_loss("000001", 12.0, 10.0) is False


# ---------------------------------------------------------------------------
# check_take_profit
# ---------------------------------------------------------------------------

class TestCheckTakeProfit:
    def test_no_take_profit_normal(self, rc):
        assert rc.check_take_profit("000001", 10.0, 10.0) is False

    def test_triggers_take_profit(self, rc):
        assert rc.check_take_profit("000001", 12.5, 10.0) is True

    def test_exactly_at_threshold(self, rc):
        cost = 100.0
        price = cost * (1 + rc.take_profit_pct / 100)
        assert rc.check_take_profit("000001", price, cost) is True

    def test_zero_cost_price(self, rc):
        assert rc.check_take_profit("000001", 15.0, 0) is False

    def test_negative_cost_price(self, rc):
        assert rc.check_take_profit("000001", 15.0, -1.0) is False

    def test_small_profit_no_trigger(self, rc):
        assert rc.check_take_profit("000001", 11.0, 10.0) is False

    def test_loss_no_trigger(self, rc):
        assert rc.check_take_profit("000001", 8.0, 10.0) is False


# ---------------------------------------------------------------------------
# check_daily_loss
# ---------------------------------------------------------------------------

class TestCheckDailyLoss:
    def test_no_halt_normal(self, rc):
        assert rc.check_daily_loss(-2_000, 100_000) is False

    def test_triggers_halt(self, rc):
        assert rc.check_daily_loss(-6_000, 100_000) is True

    def test_exactly_at_threshold(self, rc):
        assert rc.check_daily_loss(-5_000, 100_000) is True

    def test_profit_no_halt(self, rc):
        assert rc.check_daily_loss(5_000, 100_000) is False

    def test_zero_assets(self, rc):
        assert rc.check_daily_loss(-100, 0) is False


# ---------------------------------------------------------------------------
# calc_max_buy_amount
# ---------------------------------------------------------------------------

class TestCalcMaxBuyAmount:
    def test_basic(self, rc):
        amount = rc.calc_max_buy_amount(100_000, 50_000)
        max_total = 100_000 * 0.8
        max_single = 100_000 * 0.3
        expected = min(max_total - 50_000, max_single)
        assert amount == expected

    def test_fully_invested(self, rc):
        amount = rc.calc_max_buy_amount(100_000, 80_000)
        assert amount == 0

    def test_over_invested(self, rc):
        amount = rc.calc_max_buy_amount(100_000, 90_000)
        assert amount == 0

    def test_empty_portfolio(self, rc):
        amount = rc.calc_max_buy_amount(100_000, 0)
        max_single = 100_000 * 0.3
        assert amount == max_single

    def test_result_never_negative(self, rc):
        amount = rc.calc_max_buy_amount(100_000, 200_000)
        assert amount >= 0

    def test_constrained_by_single_limit(self, rc):
        amount = rc.calc_max_buy_amount(100_000, 10_000)
        max_single = 100_000 * 0.3
        assert amount <= max_single
