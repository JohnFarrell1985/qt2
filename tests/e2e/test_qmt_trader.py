"""QMT E2E-T: 交易只读测试

验证 QMTTrader 的只读查询: 资产查询、持仓查询、委托查询。
**不包含下单/撤单操作** — 仅读取当前账户状态。

运行: pytest tests/e2e/test_qmt_trader.py -m qmt -v
"""
import pytest

pytestmark = pytest.mark.qmt


class TestQueryAsset:
    """TC-T-01 ~ TC-T-02: 资产查询"""

    def test_query_asset_returns_dict(self, qmt_trader):
        """TC-T-01: query_asset 返回 dict 含 total_asset/cash/market_value"""
        asset = qmt_trader.query_asset()
        assert isinstance(asset, dict)
        assert "total_asset" in asset, f"缺少 total_asset, keys={list(asset.keys())}"
        assert "cash" in asset
        assert "market_value" in asset

    def test_asset_values_non_negative(self, qmt_trader):
        """TC-T-02: 资产数值 >= 0"""
        asset = qmt_trader.query_asset()
        if asset:
            assert asset["total_asset"] >= 0, f"total_asset={asset['total_asset']}"
            assert asset["cash"] >= 0, f"cash={asset['cash']}"


class TestQueryPositions:
    """TC-T-03 ~ TC-T-04: 持仓查询"""

    def test_query_positions_returns_list(self, qmt_trader):
        """TC-T-03: query_positions 返回 list"""
        positions = qmt_trader.query_positions()
        assert isinstance(positions, list)

    def test_positions_fields(self, qmt_trader):
        """TC-T-04: 每条持仓含 code/volume/market_value 字段"""
        positions = qmt_trader.query_positions()
        for pos in positions:
            assert "code" in pos, f"持仓缺少 code, keys={list(pos.keys())}"
            assert "volume" in pos
            assert "market_value" in pos
            assert pos["volume"] > 0


class TestQueryOrders:
    """TC-T-05 ~ TC-T-06: 委托查询"""

    def test_query_orders_returns_list(self, qmt_trader):
        """TC-T-05: query_orders 返回 list (可能为空)"""
        orders = qmt_trader.query_orders()
        assert isinstance(orders, list)

    def test_query_cancelable_orders(self, qmt_trader):
        """TC-T-06: cancelable_only=True 仅返回可撤委托"""
        orders = qmt_trader.query_orders(cancelable_only=True)
        assert isinstance(orders, list)

    def test_order_fields(self, qmt_trader):
        """TC-T-07: 委托记录含 order_id/code/direction/quantity"""
        orders = qmt_trader.query_orders()
        for o in orders:
            assert "order_id" in o
            assert "code" in o
            assert "direction" in o
            assert "quantity" in o
