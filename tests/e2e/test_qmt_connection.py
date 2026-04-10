"""QMT E2E-C: 连接测试

验证 QMTClient (数据通道) 和 QMTTrader (交易通道) 基础连通性。

运行: pytest tests/e2e/test_qmt_connection.py -m qmt -v
"""
import pytest

pytestmark = [pytest.mark.qmt, pytest.mark.timeout(15)]


class TestQMTClientConnection:
    """TC-C-01 ~ TC-C-03: 数据客户端连接"""

    def test_xtdata_loaded(self, qmt_client):
        """TC-C-01: xtquant.xtdata 模块加载成功"""
        assert qmt_client.xtdata is not None
        assert hasattr(qmt_client.xtdata, "get_market_data_ex")

    def test_core_methods_available(self, qmt_client):
        """TC-C-02: xtdata 核心 API 方法存在"""
        required = [
            "get_market_data_ex", "get_local_data", "get_full_tick",
            "get_stock_list_in_sector", "get_instrument_detail",
            "get_instrument_type", "get_sector_list",
            "get_financial_data", "get_trading_dates",
            "download_history_data2",
            "download_cb_data", "get_cb_info",
        ]
        xt = qmt_client.xtdata
        for method in required:
            assert hasattr(xt, method), f"xtdata 缺少方法: {method}"

    def test_get_sector_list(self, qmt_client, require_full_data_service):
        """TC-C-03: 板块列表非空 (验证数据服务可用)"""
        sectors = qmt_client.get_sector_list()
        assert isinstance(sectors, list)
        assert len(sectors) > 0


class TestQMTTraderConnection:
    """TC-C-04 ~ TC-C-05: 交易客户端只读连接"""

    def test_trader_connected(self, qmt_trader):
        """TC-C-04: 交易连接成功"""
        assert qmt_trader.is_connected

    def test_trader_has_account(self, qmt_trader):
        """TC-C-05: 账户对象已初始化"""
        assert qmt_trader._account is not None
        assert qmt_trader._account_id != ""
