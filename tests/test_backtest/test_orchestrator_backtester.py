"""Tests for src/backtest/orchestrator_backtester.py"""
from datetime import date
from unittest.mock import patch, MagicMock

from src.backtest.orchestrator_backtester import OrchestratorBacktester, _Position
from src.backtest.fees import FeeConfig


class TestPosition:
    def test_creation(self):
        pos = _Position(
            code="000001",
            buy_date=date(2025, 1, 6),
            buy_price=10.0,
            quantity=1000,
        )
        assert pos.code == "000001"
        assert pos.buy_date == date(2025, 1, 6)
        assert pos.buy_price == 10.0
        assert pos.quantity == 1000
        assert pos.hold_days == 0
        assert pos.can_sell is True

    def test_creation_with_can_sell_false(self):
        pos = _Position(
            code="600000",
            buy_date=date(2025, 3, 10),
            buy_price=8.5,
            quantity=500,
            can_sell=False,
        )
        assert pos.can_sell is False

    def test_default_prices(self):
        pos = _Position(
            code="000002",
            buy_date=date(2025, 1, 6),
            buy_price=20.0,
            quantity=200,
        )
        assert pos.current_price == 0.0
        assert pos.highest_price == 0.0


class TestPreloadLimitStatus:
    def test_identifies_limit_up(self):
        ohlc_cache = {
            date(2025, 1, 6): {
                "000001": {
                    "open": 11.0, "high": 11.0, "low": 10.5,
                    "close": 11.0, "pre_close": 10.0,
                    "volume": 1000000, "amount": 11000000,
                    "change_pct": 10.0,
                },
            },
        }
        result = OrchestratorBacktester._preload_limit_status(ohlc_cache)
        status = result[date(2025, 1, 6)]["000001"]
        assert status["is_limit_up"] is True
        assert status["is_limit_down"] is False
        assert status["is_suspended"] is False

    def test_identifies_limit_down(self):
        ohlc_cache = {
            date(2025, 1, 6): {
                "000001": {
                    "open": 9.0, "high": 9.5, "low": 9.0,
                    "close": 9.0, "pre_close": 10.0,
                    "volume": 500000, "amount": 4500000,
                    "change_pct": -10.0,
                },
            },
        }
        result = OrchestratorBacktester._preload_limit_status(ohlc_cache)
        status = result[date(2025, 1, 6)]["000001"]
        assert status["is_limit_down"] is True
        assert status["is_limit_up"] is False

    def test_identifies_suspended(self):
        ohlc_cache = {
            date(2025, 1, 6): {
                "000001": {
                    "open": 10.0, "high": 10.0, "low": 10.0,
                    "close": 10.0, "pre_close": 10.0,
                    "volume": 0, "amount": 0,
                    "change_pct": 0.0,
                },
            },
        }
        result = OrchestratorBacktester._preload_limit_status(ohlc_cache)
        status = result[date(2025, 1, 6)]["000001"]
        assert status["is_suspended"] is True
        assert status["is_limit_up"] is False
        assert status["is_limit_down"] is False

    def test_identifies_one_word_limit(self):
        ohlc_cache = {
            date(2025, 1, 6): {
                "000001": {
                    "open": 11.0, "high": 11.0, "low": 11.0,
                    "close": 11.0, "pre_close": 10.0,
                    "volume": 100000, "amount": 1100000,
                    "change_pct": 10.0,
                },
            },
        }
        result = OrchestratorBacktester._preload_limit_status(ohlc_cache)
        status = result[date(2025, 1, 6)]["000001"]
        assert status["is_one_word_limit"] is True
        assert status["is_limit_up"] is True

    def test_kcb_threshold_20pct(self):
        ohlc_cache = {
            date(2025, 1, 6): {
                "688001": {
                    "open": 110.0, "high": 120.0, "low": 108.0,
                    "close": 120.0, "pre_close": 100.0,
                    "volume": 200000, "amount": 24000000,
                    "change_pct": 20.0,
                },
            },
        }
        result = OrchestratorBacktester._preload_limit_status(ohlc_cache)
        status = result[date(2025, 1, 6)]["688001"]
        assert status["threshold"] == 20.0
        assert status["is_limit_up"] is True

    def test_cyb_threshold_20pct(self):
        ohlc_cache = {
            date(2025, 1, 6): {
                "300001": {
                    "open": 50.0, "high": 55.0, "low": 49.0,
                    "close": 50.5, "pre_close": 50.0,
                    "volume": 300000, "amount": 15150000,
                    "change_pct": 1.0,
                },
            },
        }
        result = OrchestratorBacktester._preload_limit_status(ohlc_cache)
        status = result[date(2025, 1, 6)]["300001"]
        assert status["threshold"] == 20.0


class TestAdvanceT1:
    @patch("src.backtest.orchestrator_backtester.StrategyOrchestrator")
    @patch("src.backtest.orchestrator_backtester.settings")
    def test_flips_can_sell(self, mock_settings, mock_orch):
        mock_settings.backtest.initial_capital = 1_000_000
        bt = OrchestratorBacktester(
            initial_capital=1_000_000,
            fee_config=FeeConfig(),
            orchestrator=MagicMock(),
        )
        pos = _Position(
            code="000001",
            buy_date=date(2025, 1, 6),
            buy_price=10.0,
            quantity=1000,
            can_sell=False,
        )
        bt.holdings["000001"] = pos

        bt._advance_t1(date(2025, 1, 7))

        assert pos.can_sell is True
        assert pos.hold_days == 1

    @patch("src.backtest.orchestrator_backtester.StrategyOrchestrator")
    @patch("src.backtest.orchestrator_backtester.settings")
    def test_increments_hold_days(self, mock_settings, mock_orch):
        mock_settings.backtest.initial_capital = 1_000_000
        bt = OrchestratorBacktester(
            initial_capital=1_000_000,
            fee_config=FeeConfig(),
            orchestrator=MagicMock(),
        )
        pos = _Position(
            code="600000",
            buy_date=date(2025, 1, 6),
            buy_price=8.0,
            quantity=500,
            can_sell=True,
        )
        bt.holdings["600000"] = pos

        bt._advance_t1(date(2025, 1, 7))
        bt._advance_t1(date(2025, 1, 8))

        assert pos.hold_days == 2
        assert pos.can_sell is True


class TestExecuteBuy:
    @patch("src.backtest.orchestrator_backtester.StrategyOrchestrator")
    @patch("src.backtest.orchestrator_backtester.settings")
    def test_skip_suspended_stock(self, mock_settings, mock_orch):
        mock_settings.backtest.initial_capital = 1_000_000
        mock_settings.sizer.lot_size = 100
        bt = OrchestratorBacktester(
            initial_capital=1_000_000,
            fee_config=FeeConfig(),
            orchestrator=MagicMock(),
        )
        action = MagicMock()
        action.code = "000001"
        action.target_quantity = 1000
        action.target_amount = 0

        ohlc = {"000001": {"close": 10.0}}
        limits = {"000001": {"is_suspended": True, "is_one_word_limit": False, "is_limit_up": False}}

        initial_cash = bt.cash
        bt._execute_buy(action, date(2025, 1, 6), ohlc, limits)

        assert bt.cash == initial_cash
        assert "000001" not in bt.holdings

    @patch("src.backtest.orchestrator_backtester.StrategyOrchestrator")
    @patch("src.backtest.orchestrator_backtester.settings")
    def test_skip_one_word_limit_up(self, mock_settings, mock_orch):
        mock_settings.backtest.initial_capital = 1_000_000
        mock_settings.sizer.lot_size = 100
        bt = OrchestratorBacktester(
            initial_capital=1_000_000,
            fee_config=FeeConfig(),
            orchestrator=MagicMock(),
        )
        action = MagicMock()
        action.code = "000001"
        action.target_quantity = 1000
        action.target_amount = 0

        ohlc = {"000001": {"close": 11.0}}
        limits = {"000001": {"is_suspended": False, "is_one_word_limit": True, "is_limit_up": True}}

        initial_cash = bt.cash
        bt._execute_buy(action, date(2025, 1, 6), ohlc, limits)

        assert bt.cash == initial_cash
        assert "000001" not in bt.holdings


class TestExecuteSell:
    @patch("src.backtest.orchestrator_backtester.StrategyOrchestrator")
    @patch("src.backtest.orchestrator_backtester.settings")
    def test_respects_t1(self, mock_settings, mock_orch):
        mock_settings.backtest.initial_capital = 1_000_000
        bt = OrchestratorBacktester(
            initial_capital=1_000_000,
            fee_config=FeeConfig(),
            orchestrator=MagicMock(),
        )
        pos = _Position(
            code="000001",
            buy_date=date(2025, 1, 6),
            buy_price=10.0,
            quantity=1000,
            can_sell=False,
        )
        bt.holdings["000001"] = pos

        action = MagicMock()
        action.code = "000001"
        action.target_quantity = 1000

        ohlc = {"000001": {"close": 10.5}}
        limits = {"000001": {"is_suspended": False, "is_one_word_limit": False, "is_limit_down": False}}

        initial_cash = bt.cash
        bt._execute_sell(action, date(2025, 1, 6), ohlc, limits)

        assert bt.cash == initial_cash
        assert "000001" in bt.holdings

    @patch("src.backtest.orchestrator_backtester.StrategyOrchestrator")
    @patch("src.backtest.orchestrator_backtester.settings")
    def test_skip_suspended_stock(self, mock_settings, mock_orch):
        mock_settings.backtest.initial_capital = 1_000_000
        bt = OrchestratorBacktester(
            initial_capital=1_000_000,
            fee_config=FeeConfig(),
            orchestrator=MagicMock(),
        )
        pos = _Position(
            code="000001",
            buy_date=date(2025, 1, 5),
            buy_price=10.0,
            quantity=1000,
            can_sell=True,
        )
        bt.holdings["000001"] = pos

        action = MagicMock()
        action.code = "000001"
        action.target_quantity = 1000

        ohlc = {"000001": {"close": 10.5}}
        limits = {"000001": {"is_suspended": True, "is_one_word_limit": False, "is_limit_down": False}}

        initial_cash = bt.cash
        bt._execute_sell(action, date(2025, 1, 6), ohlc, limits)

        assert bt.cash == initial_cash
        assert "000001" in bt.holdings
