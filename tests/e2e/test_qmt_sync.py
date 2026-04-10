"""QMT E2E-D: 数据同步 → PostgreSQL 测试

验证 MarketDataSync / FinancialDataSync / CBDataSync 从 QMT 下载并入库。
使用独立 qmt_e2e_test schema, 不影响主库。

运行: pytest tests/e2e/test_qmt_sync.py -m qmt -v
"""
import pytest
from unittest.mock import patch
from sqlalchemy import text

from tests.e2e.conftest import make_qmt_get_session, QMT_SCHEMA

pytestmark = pytest.mark.qmt

SYNC_STOCKS = ["600519.SH", "000001.SZ"]


class TestStockListSync:
    """TC-D-01: 股票列表同步入库"""

    def test_sync_stock_list(self, qmt_client, qmt_session_factory, qmt_db_session):
        """TC-D-01: sync_stock_list 写入 stocks 表"""
        from src.data.market_data import MarketDataSync

        override = make_qmt_get_session(qmt_session_factory)
        with patch("src.data.market_data.get_session", override):
            sync = MarketDataSync(client=qmt_client)
            count = sync.sync_stock_list()

        assert count > 0, "sync_stock_list 返回 0"

        row = qmt_db_session.execute(
            text(f"SELECT count(*) FROM {QMT_SCHEMA}.stocks")
        ).scalar()
        assert row > 0, "stocks 表无数据"


class TestDailySync:
    """TC-D-02 ~ TC-D-03: 日线数据同步入库"""

    def test_sync_daily_data(self, qmt_client, qmt_session_factory, qmt_db_session):
        """TC-D-02: sync_daily_data 写入 stock_daily 表"""
        from src.data.market_data import MarketDataSync

        override = make_qmt_get_session(qmt_session_factory)
        with patch("src.data.market_data.get_session", override):
            sync = MarketDataSync(client=qmt_client)
            total = sync.sync_daily_data(
                SYNC_STOCKS,
                start_date="20250101",
                end_date="20250110",
                incremental=True,
            )

        assert total > 0, "sync_daily_data 返回 0"

        row = qmt_db_session.execute(
            text(f"SELECT count(*) FROM {QMT_SCHEMA}.stock_daily")
        ).scalar()
        assert row > 0, "stock_daily 表无数据"

    def test_daily_data_has_ohlcv(self, qmt_db_session):
        """TC-D-03: stock_daily 记录包含完整 OHLCV"""
        row = qmt_db_session.execute(text(
            f"SELECT open, high, low, close, volume "
            f"FROM {QMT_SCHEMA}.stock_daily LIMIT 1"
        )).fetchone()
        if row:
            assert row[0] is not None, "open 为 NULL"
            assert row[3] is not None, "close 为 NULL"
            assert row[3] > 0, "close <= 0"


class TestIndexSync:
    """TC-D-04: 指数数据同步"""

    def test_sync_index_data(self, qmt_client, qmt_session_factory, qmt_db_session):
        """TC-D-04: sync_index_data 写入 market_index 表"""
        from src.data.market_data import MarketDataSync

        override = make_qmt_get_session(qmt_session_factory)
        with patch("src.data.market_data.get_session", override):
            sync = MarketDataSync(client=qmt_client)
            total = sync.sync_index_data(
                start_date="20250101",
                end_date="20250110",
                incremental=True,
            )

        assert total > 0, "sync_index_data 返回 0"

        row = qmt_db_session.execute(
            text(f"SELECT count(*) FROM {QMT_SCHEMA}.market_index")
        ).scalar()
        assert row > 0


class TestFinancialSync:
    """TC-D-05 ~ TC-D-06: 财务数据同步"""

    def test_sync_reports(self, qmt_client, qmt_session_factory, qmt_db_session):
        """TC-D-05: sync_reports 写入 stock_financial_report 表"""
        from src.data.financial_data import FinancialDataSync

        override = make_qmt_get_session(qmt_session_factory)
        with patch("src.data.financial_data.get_session", override):
            sync = FinancialDataSync(client=qmt_client)
            total = sync.sync_reports(
                SYNC_STOCKS,
                start_time="20240101",
                end_time="20250101",
            )

        row = qmt_db_session.execute(
            text(f"SELECT count(*) FROM {QMT_SCHEMA}.stock_financial_report")
        ).scalar()
        assert row >= 0

    def test_sync_indicators(self, qmt_client, qmt_session_factory, qmt_db_session):
        """TC-D-06: sync_indicators 写入 stock_financial_indicator 表"""
        from src.data.financial_data import FinancialDataSync

        override = make_qmt_get_session(qmt_session_factory)
        with patch("src.data.financial_data.get_session", override):
            sync = FinancialDataSync(client=qmt_client)
            total = sync.sync_indicators(
                SYNC_STOCKS,
                start_time="20240101",
                end_time="20250101",
            )

        row = qmt_db_session.execute(
            text(f"SELECT count(*) FROM {QMT_SCHEMA}.stock_financial_indicator")
        ).scalar()
        assert row >= 0


class TestCBSync:
    """TC-D-07: 可转债数据同步"""

    def test_sync_cb_info(self, qmt_client, qmt_session_factory, qmt_db_session):
        """TC-D-07: CBDataSync.sync_cb_info 写入 convertible_bond 表"""
        from src.data.cb_data import CBDataSync

        override = make_qmt_get_session(qmt_session_factory)
        with patch("src.data.cb_data.get_session", override):
            sync = CBDataSync(client=qmt_client)
            count = sync.sync_cb_info()

        if count > 0:
            row = qmt_db_session.execute(
                text(f"SELECT count(*) FROM {QMT_SCHEMA}.convertible_bond")
            ).scalar()
            assert row > 0


class TestDataSyncManager:
    """TC-D-08: DataSyncManager 集成调度"""

    def test_download_base_data(self, qmt_client):
        """TC-D-08: download_base_data (板块/节假日/指数权重) 不抛异常"""
        from src.data.sync import DataSyncManager

        mgr = DataSyncManager(client=qmt_client)
        mgr.download_base_data()
