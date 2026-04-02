"""Tests for src/trading/order_manager.py"""
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_trader():
    trader = MagicMock()
    trader.order_stock.return_value = 10001
    trader.cancel_order.return_value = 0
    trader.query_orders.return_value = [
        {"order_id": 10001, "code": "600519.SH", "direction": "buy",
         "quantity": 100, "price": 1800.0, "status": "filled", "traded_volume": 100}
    ]
    return trader


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


@pytest.fixture
def order_manager(mock_trader, mock_session):
    with patch("src.trading.order_manager.get_session") as mock_get_session:
        mock_get_session.return_value = mock_session
        from src.trading.order_manager import OrderManager
        mgr = OrderManager(trader=mock_trader, account_type="paper")
        mgr._mock_get_session = mock_get_session
        yield mgr


class TestSubmitOrder:

    def test_submit_order_success(self, mock_trader, mock_session):
        with patch("src.trading.order_manager.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.trading.order_manager import OrderManager
            mgr = OrderManager(trader=mock_trader, account_type="paper")

            order_id = mgr.submit_order(
                code="600519.SH", direction="buy", quantity=100,
                price=1800.0, price_type="FIX_PRICE",
            )

        assert order_id == 10001
        mock_trader.order_stock.assert_called_once_with(
            code="600519.SH", direction="buy", quantity=100,
            price_type="FIX_PRICE", price=1800.0,
        )
        mock_session.add.assert_called_once()

    def test_submit_order_failure(self, mock_session):
        failing_trader = MagicMock()
        failing_trader.order_stock.side_effect = ConnectionError("not connected")
        with patch("src.trading.order_manager.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.trading.order_manager import OrderManager
            mgr = OrderManager(trader=failing_trader, account_type="paper")

            result = mgr.submit_order("600519.SH", "buy", 100)

        assert result is None

    def test_submit_order_stores_record(self, mock_trader, mock_session):
        with patch("src.trading.order_manager.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.trading.order_manager import OrderManager
            mgr = OrderManager(trader=mock_trader, account_type="paper")
            mgr.submit_order("600519.SH", "buy", 100)

        record = mock_session.add.call_args[0][0]
        assert record.order_id == "10001"
        assert record.code == "600519.SH"
        assert record.direction == "buy"
        assert record.status == "pending"


class TestCancelOrder:

    def test_cancel_order_success(self, mock_session):
        trader = MagicMock()
        trader.cancel_order.return_value = 0

        mock_order = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_order

        with patch("src.trading.order_manager.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.trading.order_manager import OrderManager
            mgr = OrderManager(trader=trader, account_type="paper")

            result = mgr.cancel_order(10001)

        assert result is True
        assert mock_order.status == "cancelled"

    def test_cancel_order_no_db_record(self, mock_session):
        trader = MagicMock()
        trader.cancel_order.return_value = 0
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.trading.order_manager.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.trading.order_manager import OrderManager
            mgr = OrderManager(trader=trader, account_type="paper")
            result = mgr.cancel_order(99999)

        assert result is True

    def test_cancel_order_failure(self, mock_session):
        trader = MagicMock()
        trader.cancel_order.side_effect = ConnectionError("not connected")

        with patch("src.trading.order_manager.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.trading.order_manager import OrderManager
            mgr = OrderManager(trader=trader, account_type="paper")
            result = mgr.cancel_order(10001)

        assert result is False


class TestGetTodayOrders:

    def test_get_today_orders(self, mock_trader):
        from src.trading.order_manager import OrderManager
        mgr = OrderManager(trader=mock_trader, account_type="paper")
        orders = mgr.get_today_orders()

        assert len(orders) == 1
        assert orders[0]["order_id"] == 10001
        mock_trader.query_orders.assert_called_once()
