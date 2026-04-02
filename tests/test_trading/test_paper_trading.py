"""Tests for src/trading/paper_trading.py"""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_trader():
    trader = MagicMock()
    trader.connect.return_value = True
    trader.query_asset.return_value = {
        "total_asset": 1_000_000,
        "cash": 500_000,
        "market_value": 500_000,
        "frozen_cash": 0,
    }
    trader.query_positions.return_value = [
        {
            "code": "600519.SH",
            "volume": 200,
            "can_use_volume": 200,
            "open_price": 1800.0,
            "market_value": 380000.0,
        },
    ]
    return trader


@pytest.fixture
def mock_risk():
    risk = MagicMock()
    risk.calc_max_buy_amount.return_value = 100_000
    risk.check_stop_loss.return_value = False
    risk.check_take_profit.return_value = False
    return risk


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


@pytest.fixture
def engine(mock_trader, mock_risk, mock_session):
    with patch("src.trading.order_manager.get_session") as gs1, \
         patch("src.trading.position_manager.get_session") as gs2:
        gs1.return_value = mock_session
        gs2.return_value = mock_session
        from src.trading.paper_trading import PaperTradingEngine
        eng = PaperTradingEngine(trader=mock_trader, risk_controller=mock_risk)
        eng.order_mgr = MagicMock()
        eng.order_mgr.submit_order.return_value = 10001
        yield eng


class TestConnect:

    def test_connect_delegates(self, engine, mock_trader):
        assert engine.connect() is True
        mock_trader.connect.assert_called_once()


class TestExecuteSignals:

    def test_buy_new_stock(self, engine, mock_trader):
        mock_trader.query_positions.return_value = []
        signals = [{"code": "000001.SZ", "signal": "buy", "rank": 1}]

        results = engine.execute_signals(signals)

        assert len(results) == 1
        assert results[0]["action"] == "buy"
        assert results[0]["code"] == "000001.SZ"
        engine.order_mgr.submit_order.assert_called_once()

    def test_buy_already_held_skip(self, engine, mock_trader):
        mock_trader.query_positions.return_value = [
            {"code": "600519.SH", "volume": 200, "can_use_volume": 200,
             "open_price": 1800.0, "market_value": 380000.0},
        ]
        signals = [{"code": "600519.SH", "signal": "buy", "rank": 1}]

        results = engine.execute_signals(signals)

        assert len(results) == 1
        assert results[0]["action"] == "skip"
        assert results[0]["reason"] == "already_held"

    def test_buy_insufficient_quota(self, engine, mock_trader, mock_risk):
        mock_trader.query_positions.return_value = []
        mock_risk.calc_max_buy_amount.return_value = 500  # below 1000 threshold

        signals = [{"code": "000001.SZ", "signal": "buy", "rank": 1}]
        results = engine.execute_signals(signals)

        assert results[0]["action"] == "skip"
        assert results[0]["reason"] == "insufficient_quota"

    def test_sell_existing_position(self, engine, mock_trader):
        mock_trader.query_positions.return_value = [
            {"code": "600519.SH", "volume": 200, "can_use_volume": 200,
             "open_price": 1800.0, "market_value": 380000.0},
        ]
        signals = [{"code": "600519.SH", "signal": "sell", "rank": 1}]

        results = engine.execute_signals(signals)

        assert len(results) == 1
        assert results[0]["action"] == "sell"
        assert results[0]["quantity"] == 200
        engine.order_mgr.submit_order.assert_called_once_with(
            code="600519.SH", direction="sell", quantity=200,
        )

    def test_sell_not_held_ignored(self, engine, mock_trader):
        mock_trader.query_positions.return_value = []
        signals = [{"code": "999999.SH", "signal": "sell", "rank": 1}]

        results = engine.execute_signals(signals)
        assert len(results) == 0

    def test_buy_quantity_zero_skip(self, engine, mock_trader, mock_risk):
        """Cash too low to buy even 100 shares."""
        mock_trader.query_positions.return_value = []
        mock_trader.query_asset.return_value = {
            "total_asset": 1_000_000, "cash": 50,
            "market_value": 999_950, "frozen_cash": 0,
        }
        mock_risk.calc_max_buy_amount.return_value = 5000

        signals = [{"code": "000001.SZ", "signal": "buy", "rank": 1}]
        results = engine.execute_signals(signals)

        assert results[0]["action"] == "skip"
        assert results[0]["reason"] == "quantity_zero"


class TestCheckRiskAndStop:

    def test_stop_loss_trigger(self, engine, mock_trader, mock_risk):
        mock_trader.query_positions.return_value = [
            {"code": "600519.SH", "volume": 100, "can_use_volume": 100,
             "open_price": 100.0, "market_value": 8000.0},
        ]
        mock_risk.check_stop_loss.return_value = True
        mock_risk.check_take_profit.return_value = False

        actions = engine.check_risk_and_stop()

        assert len(actions) == 1
        assert actions[0]["action"] == "stop_loss"
        engine.order_mgr.submit_order.assert_called_once()

    def test_take_profit_trigger(self, engine, mock_trader, mock_risk):
        mock_trader.query_positions.return_value = [
            {"code": "600519.SH", "volume": 100, "can_use_volume": 100,
             "open_price": 100.0, "market_value": 15000.0},
        ]
        mock_risk.check_stop_loss.return_value = False
        mock_risk.check_take_profit.return_value = True

        actions = engine.check_risk_and_stop()

        assert len(actions) == 1
        assert actions[0]["action"] == "take_profit"

    def test_no_triggers(self, engine, mock_trader, mock_risk):
        mock_risk.check_stop_loss.return_value = False
        mock_risk.check_take_profit.return_value = False
        actions = engine.check_risk_and_stop()
        assert actions == []


class TestDailyClose:

    def test_daily_close_snapshots(self, engine):
        engine.position_mgr = MagicMock()
        engine.daily_close()
        engine.position_mgr.snapshot.assert_called_once()
