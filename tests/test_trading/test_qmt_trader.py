"""Tests for src/trading/qmt_trader.py"""
import sys
import pytest
from unittest.mock import patch, MagicMock, PropertyMock


@pytest.fixture
def mock_settings():
    with patch("src.trading.qmt_trader.settings") as m:
        m.qmt.account_id = "TEST_ACCOUNT"
        m.qmt.qmt_path = "/fake/path"
        m.qmt.account_type = "STOCK"
        yield m


@pytest.fixture
def mock_xtquant():
    """Set up mocked xtquant modules in sys.modules."""
    xtquant = MagicMock()
    xtquant.xttrader = MagicMock()
    xtquant.xttype = MagicMock()
    xtquant.xtconstant = MagicMock()
    xtquant.xtconstant.STOCK_BUY = 23
    xtquant.xtconstant.STOCK_SELL = 24
    xtquant.xtconstant.FIX_PRICE = 11
    xtquant.xtconstant.LATEST_PRICE = 5

    modules = {
        "xtquant": xtquant,
        "xtquant.xttrader": xtquant.xttrader,
        "xtquant.xttype": xtquant.xttype,
        "xtquant.xtconstant": xtquant.xtconstant,
    }

    with patch.dict(sys.modules, modules):
        yield xtquant


@pytest.fixture
def trader(mock_settings):
    from src.trading.qmt_trader import QMTTrader
    return QMTTrader(
        account_id="ACC001",
        qmt_path="/qmt/path",
        account_type="STOCK",
        session_id=99999,
    )


@pytest.fixture
def connected_trader(trader, mock_xtquant):
    """Return a trader with _connected=True and a mock _trader backend."""
    mock_backend = MagicMock()
    trader._trader = mock_backend
    trader._account = MagicMock()
    trader._connected = True
    return trader


# ---------------------------------------------------------------------------
# TraderCallback
# ---------------------------------------------------------------------------

class TestTraderCallback:

    def test_on_disconnected(self, mock_settings):
        from src.trading.qmt_trader import TraderCallback
        cb = TraderCallback()
        cb.on_disconnected()

    def test_on_stock_order(self, mock_settings):
        from src.trading.qmt_trader import TraderCallback
        cb = TraderCallback()
        order = MagicMock()
        order.stock_code = "600519.SH"
        order.order_status = "filled"
        cb.on_stock_order(order)

    def test_on_stock_trade(self, mock_settings):
        from src.trading.qmt_trader import TraderCallback
        cb = TraderCallback()
        trade = MagicMock()
        trade.stock_code = "600519.SH"
        trade.traded_price = 1800.0
        trade.traded_volume = 100
        cb.on_stock_trade(trade)

    def test_on_order_error(self, mock_settings):
        from src.trading.qmt_trader import TraderCallback
        cb = TraderCallback()
        error = MagicMock()
        error.error_msg = "insufficient funds"
        cb.on_order_error(error)

    def test_on_order_stock_async_response(self, mock_settings):
        from src.trading.qmt_trader import TraderCallback
        cb = TraderCallback()
        response = MagicMock()
        response.seq = 12345
        cb.on_order_stock_async_response(response)


# ---------------------------------------------------------------------------
# QMTTrader.__init__
# ---------------------------------------------------------------------------

class TestQMTTraderInit:

    def test_explicit_params(self, mock_settings):
        from src.trading.qmt_trader import QMTTrader
        t = QMTTrader(
            account_id="MY_ACC",
            qmt_path="/my/path",
            account_type="CREDIT",
            session_id=42,
        )
        assert t._account_id == "MY_ACC"
        assert t._path == "/my/path"
        assert t._account_type == "CREDIT"
        assert t._session_id == 42
        assert t._connected is False
        assert t._trader is None

    def test_defaults_from_settings(self, mock_settings):
        from src.trading.qmt_trader import QMTTrader
        t = QMTTrader()
        assert t._account_id == "TEST_ACCOUNT"
        assert t._path == "/fake/path"
        assert t._account_type == "STOCK"


# ---------------------------------------------------------------------------
# connect()
# ---------------------------------------------------------------------------

class TestConnect:

    def test_connect_success(self, trader, mock_xtquant):
        mock_backend = MagicMock()
        mock_backend.connect.return_value = 0
        mock_backend.subscribe.return_value = 0
        mock_xtquant.xttrader.XtQuantTrader.return_value = mock_backend
        mock_xtquant.xttype.StockAccount.return_value = MagicMock()

        result = trader.connect()

        assert result is True
        assert trader._connected is True
        mock_backend.register_callback.assert_called_once()
        mock_backend.start.assert_called_once()

    def test_connect_failure(self, trader, mock_xtquant):
        mock_backend = MagicMock()
        mock_backend.connect.return_value = -1
        mock_xtquant.xttrader.XtQuantTrader.return_value = mock_backend
        mock_xtquant.xttype.StockAccount.return_value = MagicMock()

        result = trader.connect()

        assert result is False

    def test_connect_import_error(self, mock_settings):
        """When xtquant is not installed, connect() raises ImportError."""
        modules = {k: v for k, v in sys.modules.items()}
        modules["xtquant"] = None
        modules["xtquant.xttrader"] = None
        modules["xtquant.xttype"] = None
        modules["xtquant.xtdata"] = None
        with patch.dict(sys.modules, modules, clear=False):
            from src.trading.qmt_trader import QMTTrader
            t = QMTTrader(session_id=1)
            with pytest.raises(ImportError, match="xtquant"):
                t.connect()

    def test_connect_generic_exception(self, trader, mock_xtquant):
        mock_xtquant.xttrader.XtQuantTrader.side_effect = RuntimeError("boom")

        result = trader.connect()

        assert result is False


# ---------------------------------------------------------------------------
# order_stock()
# ---------------------------------------------------------------------------

class TestOrderStock:

    def test_buy_order(self, connected_trader, mock_xtquant):
        connected_trader._trader.order_stock.return_value = 10001
        oid = connected_trader.order_stock("600519.SH", "buy", 100)
        assert oid == 10001
        call_args = connected_trader._trader.order_stock.call_args
        assert call_args[0][1] == "600519.SH"
        assert call_args[0][2] == mock_xtquant.xtconstant.STOCK_BUY

    def test_sell_order(self, connected_trader, mock_xtquant):
        connected_trader._trader.order_stock.return_value = 10002
        oid = connected_trader.order_stock("600519.SH", "sell", 200)
        assert oid == 10002
        call_args = connected_trader._trader.order_stock.call_args
        assert call_args[0][2] == mock_xtquant.xtconstant.STOCK_SELL

    def test_fix_price_type(self, connected_trader, mock_xtquant):
        connected_trader._trader.order_stock.return_value = 10003
        connected_trader.order_stock(
            "600519.SH", "buy", 100, price_type="FIX_PRICE", price=1800.0
        )
        call_args = connected_trader._trader.order_stock.call_args
        assert call_args[0][4] == mock_xtquant.xtconstant.FIX_PRICE

    def test_not_connected_raises(self, trader, mock_xtquant):
        with pytest.raises(ConnectionError, match="未连接"):
            trader.order_stock("600519.SH", "buy", 100)


# ---------------------------------------------------------------------------
# order_stock_async()
# ---------------------------------------------------------------------------

class TestOrderStockAsync:

    def test_async_buy(self, connected_trader, mock_xtquant):
        connected_trader._trader.order_stock_async.return_value = 55
        seq = connected_trader.order_stock_async("000001.SZ", "buy", 300)
        assert seq == 55
        call_args = connected_trader._trader.order_stock_async.call_args
        assert call_args[0][2] == mock_xtquant.xtconstant.STOCK_BUY

    def test_async_sell(self, connected_trader, mock_xtquant):
        connected_trader._trader.order_stock_async.return_value = 56
        seq = connected_trader.order_stock_async("000001.SZ", "sell", 300)
        assert seq == 56
        call_args = connected_trader._trader.order_stock_async.call_args
        assert call_args[0][2] == mock_xtquant.xtconstant.STOCK_SELL

    def test_not_connected_raises(self, trader, mock_xtquant):
        with pytest.raises(ConnectionError):
            trader.order_stock_async("000001.SZ", "buy", 100)


# ---------------------------------------------------------------------------
# cancel_order()
# ---------------------------------------------------------------------------

class TestCancelOrder:

    def test_cancel(self, connected_trader):
        connected_trader._trader.cancel_order_stock.return_value = 0
        result = connected_trader.cancel_order(10001)
        assert result == 0
        connected_trader._trader.cancel_order_stock.assert_called_once_with(
            connected_trader._account, 10001
        )

    def test_not_connected_raises(self, trader):
        with pytest.raises(ConnectionError):
            trader.cancel_order(10001)


# ---------------------------------------------------------------------------
# query_asset()
# ---------------------------------------------------------------------------

class TestQueryAsset:

    def test_returns_dict(self, connected_trader):
        asset = MagicMock()
        asset.total_asset = 1_000_000
        asset.cash = 500_000
        asset.market_value = 500_000
        asset.frozen_cash = 10_000
        connected_trader._trader.query_stock_asset.return_value = asset

        result = connected_trader.query_asset()

        assert result["total_asset"] == 1_000_000
        assert result["cash"] == 500_000
        assert result["market_value"] == 500_000
        assert result["frozen_cash"] == 10_000

    def test_returns_empty_on_none(self, connected_trader):
        connected_trader._trader.query_stock_asset.return_value = None
        assert connected_trader.query_asset() == {}

    def test_not_connected_raises(self, trader):
        with pytest.raises(ConnectionError):
            trader.query_asset()


# ---------------------------------------------------------------------------
# query_positions()
# ---------------------------------------------------------------------------

class TestQueryPositions:

    def test_returns_list(self, connected_trader):
        pos = MagicMock()
        pos.stock_code = "600519.SH"
        pos.volume = 200
        pos.can_use_volume = 100
        pos.open_price = 1800.0
        pos.avg_price = 1810.0
        pos.market_value = 362000.0
        pos.frozen_volume = 0
        connected_trader._trader.query_stock_positions.return_value = [pos]

        result = connected_trader.query_positions()

        assert len(result) == 1
        assert result[0]["code"] == "600519.SH"
        assert result[0]["volume"] == 200
        assert result[0]["market_value"] == 362000.0

    def test_none_returns_empty(self, connected_trader):
        connected_trader._trader.query_stock_positions.return_value = None
        assert connected_trader.query_positions() == []

    def test_filters_zero_volume(self, connected_trader):
        pos_ok = MagicMock()
        pos_ok.stock_code = "600519.SH"
        pos_ok.volume = 100
        pos_ok.can_use_volume = 100
        pos_ok.open_price = 10
        pos_ok.market_value = 1100
        pos_ok.frozen_volume = 0
        pos_ok.avg_price = 10

        pos_zero = MagicMock()
        pos_zero.volume = 0

        connected_trader._trader.query_stock_positions.return_value = [pos_ok, pos_zero]
        result = connected_trader.query_positions()
        assert len(result) == 1

    def test_not_connected_raises(self, trader):
        with pytest.raises(ConnectionError):
            trader.query_positions()


# ---------------------------------------------------------------------------
# query_orders()
# ---------------------------------------------------------------------------

class TestQueryOrders:

    def test_returns_list(self, connected_trader, mock_xtquant):
        order = MagicMock()
        order.order_id = 10001
        order.stock_code = "600519.SH"
        order.order_type = mock_xtquant.xtconstant.STOCK_BUY
        order.order_volume = 100
        order.price = 1800.0
        order.order_status = "filled"
        order.traded_volume = 100
        connected_trader._trader.query_stock_orders.return_value = [order]

        result = connected_trader.query_orders()

        assert len(result) == 1
        assert result[0]["direction"] == "buy"
        assert result[0]["order_id"] == 10001

    def test_sell_direction(self, connected_trader, mock_xtquant):
        order = MagicMock()
        order.order_id = 10002
        order.stock_code = "000001.SZ"
        order.order_type = 999  # anything != STOCK_BUY
        order.order_volume = 50
        order.price = 15.0
        order.order_status = "filled"
        order.traded_volume = 50
        connected_trader._trader.query_stock_orders.return_value = [order]

        result = connected_trader.query_orders()
        assert result[0]["direction"] == "sell"

    def test_none_returns_empty(self, connected_trader, mock_xtquant):
        connected_trader._trader.query_stock_orders.return_value = None
        assert connected_trader.query_orders() == []

    def test_cancelable_only_param(self, connected_trader, mock_xtquant):
        connected_trader._trader.query_stock_orders.return_value = []
        connected_trader.query_orders(cancelable_only=True)
        connected_trader._trader.query_stock_orders.assert_called_with(
            connected_trader._account, True
        )

    def test_not_connected_raises(self, trader):
        with pytest.raises(ConnectionError):
            trader.query_orders()


# ---------------------------------------------------------------------------
# is_connected property
# ---------------------------------------------------------------------------

class TestIsConnected:

    def test_initially_false(self, trader):
        assert trader.is_connected is False

    def test_true_after_connect(self, connected_trader):
        assert connected_trader.is_connected is True
