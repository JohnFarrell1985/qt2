"""Tests for src/trading/live_trading.py"""
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
    trader.query_positions.return_value = []
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
        from src.trading.live_trading import LiveTradingEngine
        eng = LiveTradingEngine(trader=mock_trader, risk_controller=mock_risk)
        eng.order_mgr = MagicMock()
        eng.order_mgr.submit_order.return_value = 20001
        yield eng


class TestLiveTradingInheritance:

    def test_inherits_paper_trading(self, engine):
        from src.trading.paper_trading import PaperTradingEngine
        assert isinstance(engine, PaperTradingEngine)

    def test_account_type_is_live(self, engine):
        assert engine.order_mgr is not None


class TestConfirmLiveMode:

    def test_initially_not_confirmed(self, engine):
        assert engine._confirmed is False

    def test_confirm_sets_flag(self, engine):
        engine.confirm_live_mode()
        assert engine._confirmed is True


class TestExecuteSignalsBeforeConfirm:

    def test_raises_runtime_error(self, engine):
        signals = [{"code": "600519.SH", "signal": "buy", "rank": 1}]
        with pytest.raises(RuntimeError, match="实盘模式未确认"):
            engine.execute_signals(signals)


class TestExecuteSignalsAfterConfirm:

    def test_works_after_confirm(self, engine, mock_trader):
        engine.confirm_live_mode()
        mock_trader.query_positions.return_value = []
        signals = [{"code": "000001.SZ", "signal": "buy", "rank": 1}]

        results = engine.execute_signals(signals)

        assert len(results) == 1
        assert results[0]["action"] == "buy"

    def test_sell_after_confirm(self, engine, mock_trader):
        engine.confirm_live_mode()
        mock_trader.query_positions.return_value = [
            {"code": "600519.SH", "volume": 100, "can_use_volume": 100,
             "open_price": 1800.0, "market_value": 180000.0},
        ]
        signals = [{"code": "600519.SH", "signal": "sell", "rank": 1}]

        results = engine.execute_signals(signals)

        assert results[0]["action"] == "sell"


class TestDailyClose:

    def test_daily_close(self, engine):
        engine.position_mgr = MagicMock()
        engine.daily_close()
        engine.position_mgr.snapshot.assert_called_once()
