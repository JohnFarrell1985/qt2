"""Tests for src/trading/position_manager.py"""
import pytest
from datetime import date
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_trader():
    trader = MagicMock()
    trader.query_positions.return_value = [
        {
            "code": "600519.SH",
            "volume": 200,
            "can_use_volume": 200,
            "open_price": 1800.0,
            "avg_price": 1810.0,
            "market_value": 380000.0,
            "frozen_volume": 0,
        },
        {
            "code": "000001.SZ",
            "volume": 1000,
            "can_use_volume": 1000,
            "open_price": 15.0,
            "avg_price": 15.5,
            "market_value": 16000.0,
            "frozen_volume": 0,
        },
    ]
    return trader


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


class TestGetCurrentPositions:

    def test_delegates_to_trader(self, mock_trader):
        from src.trading.position_manager import PositionManager
        mgr = PositionManager(trader=mock_trader, account_type="paper")
        positions = mgr.get_current_positions()

        assert len(positions) == 2
        assert positions[0]["code"] == "600519.SH"
        mock_trader.query_positions.assert_called_once()

    def test_empty_positions(self):
        trader = MagicMock()
        trader.query_positions.return_value = []
        from src.trading.position_manager import PositionManager
        mgr = PositionManager(trader=trader)
        assert mgr.get_current_positions() == []


class TestSnapshot:

    def test_snapshot_creates_records(self, mock_trader, mock_session):
        with patch("src.trading.position_manager.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.trading.position_manager import PositionManager
            mgr = PositionManager(trader=mock_trader, account_type="paper")

            count = mgr.snapshot()

        assert count == 2
        assert mock_session.add.call_count == 2

        first_record = mock_session.add.call_args_list[0][0][0]
        assert first_record.code == "600519.SH"
        assert first_record.account_type == "paper"
        assert first_record.quantity == 200
        assert first_record.cost_price == 1800.0
        assert first_record.market_value == 380000.0

    def test_snapshot_empty_positions(self, mock_session):
        trader = MagicMock()
        trader.query_positions.return_value = []
        with patch("src.trading.position_manager.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.trading.position_manager import PositionManager
            mgr = PositionManager(trader=trader)
            count = mgr.snapshot()

        assert count == 0
        mock_session.add.assert_not_called()

    def test_snapshot_profit_calculation(self, mock_session):
        trader = MagicMock()
        trader.query_positions.return_value = [
            {
                "code": "600519.SH",
                "volume": 100,
                "can_use_volume": 100,
                "open_price": 10.0,
                "market_value": 1200.0,
                "frozen_volume": 0,
            },
        ]
        with patch("src.trading.position_manager.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.trading.position_manager import PositionManager
            mgr = PositionManager(trader=trader)
            mgr.snapshot()

        record = mock_session.add.call_args[0][0]
        assert record.market_price == pytest.approx(12.0)  # 1200 / 100
        assert record.profit == pytest.approx(200.0)  # 1200 - 10*100
        assert record.profit_pct == pytest.approx(20.0)  # (12/10 - 1)*100


class TestGetTotalMarketValue:

    def test_sums_market_values(self, mock_trader):
        from src.trading.position_manager import PositionManager
        mgr = PositionManager(trader=mock_trader)
        total = mgr.get_total_market_value()
        assert total == pytest.approx(380000.0 + 16000.0)

    def test_empty_positions(self):
        trader = MagicMock()
        trader.query_positions.return_value = []
        from src.trading.position_manager import PositionManager
        mgr = PositionManager(trader=trader)
        assert mgr.get_total_market_value() == 0.0
