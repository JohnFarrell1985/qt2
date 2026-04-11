"""E2E: Tier 1 扩展源 — 可转债 / ETF / 财务 (eastmoney, tushare, adata)

原则: 2 分钟内无数据返回 = 数据源不可用, 彻底放弃。

仅测试数据源连通性和返回格式, 不落盘。
eastmoney 走 HTTP 直连, 限流最严 (~10s/次);
tushare 需要 Token; adata 底层走东财。
"""
import pytest

import pandas as pd

from src.datacollect.rate_limiter import TokenBucketLimiter

_NETWORK_ERRORS = (ConnectionError, OSError, RuntimeError, ImportError)

SAMPLE_CB_CODE_SH = "110001"
SAMPLE_CB_CODE_SZ = "123456"
SAMPLE_ETF_CODE = "510300"
SAMPLE_STOCK_CODE = "000001"


@pytest.fixture(autouse=True)
def _reset_limiters():
    yield
    TokenBucketLimiter.reset_all()


# ====================================================================
# 东方财富 — 可转债
# ====================================================================

class TestEastmoneyCB:
    """eastmoney 可转债列表 + K 线"""

    @pytest.mark.timeout(120)
    def test_fetch_cb_list(self):
        from src.datacollect.collectors.eastmoney_collector import EastmoneyCollector

        collector = EastmoneyCollector()
        try:
            df = collector.fetch_cb_list()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"eastmoney 可转债网络不可达: {exc}")

        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0, "东财可转债列表为空"
        assert "code" in df.columns
        assert "name" in df.columns

    @pytest.mark.timeout(120)
    def test_fetch_cb_kline(self):
        from src.datacollect.collectors.eastmoney_collector import EastmoneyCollector

        collector = EastmoneyCollector()
        try:
            df = collector.fetch_cb_kline(SAMPLE_CB_CODE_SH, start_date="20250101")
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"eastmoney 可转债 K 线网络不可达: {exc}")

        assert isinstance(df, pd.DataFrame)
        if len(df) > 0:
            assert "code" in df.columns
            assert "close" in df.columns


# ====================================================================
# 东方财富 — ETF
# ====================================================================

class TestEastmoneyETF:
    """eastmoney ETF 列表 + K 线"""

    @pytest.mark.timeout(120)
    def test_fetch_etf_list(self):
        from src.datacollect.collectors.eastmoney_collector import EastmoneyCollector

        collector = EastmoneyCollector()
        try:
            df = collector.fetch_etf_list()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"eastmoney ETF 网络不可达: {exc}")

        assert isinstance(df, pd.DataFrame)
        assert len(df) > 0, "东财 ETF 列表为空"
        assert "code" in df.columns

    @pytest.mark.timeout(120)
    def test_fetch_etf_kline(self):
        from src.datacollect.collectors.eastmoney_collector import EastmoneyCollector

        collector = EastmoneyCollector()
        try:
            df = collector.fetch_etf_kline(SAMPLE_ETF_CODE, start_date="20250101")
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"eastmoney ETF K 线网络不可达: {exc}")

        assert isinstance(df, pd.DataFrame)
        if len(df) > 0:
            assert "code" in df.columns
            assert "close" in df.columns


# ====================================================================
# 东方财富 — 财务报表
# ====================================================================

class TestEastmoneyFinancial:
    """eastmoney 财务报表 (利润表 / 资产负债表 / 现金流量表)"""

    @pytest.mark.timeout(120)
    def test_fetch_financial_income(self):
        from src.datacollect.collectors.eastmoney_collector import EastmoneyCollector

        collector = EastmoneyCollector()
        try:
            df = collector.fetch_financial(SAMPLE_STOCK_CODE, report_type="income")
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"eastmoney 财务报表网络不可达: {exc}")

        assert isinstance(df, pd.DataFrame)
        if len(df) > 0:
            assert "SECURITY_CODE" in df.columns or len(df.columns) > 3

    @pytest.mark.timeout(120)
    def test_fetch_financial_balance(self):
        from src.datacollect.collectors.eastmoney_collector import EastmoneyCollector

        collector = EastmoneyCollector()
        try:
            df = collector.fetch_financial(SAMPLE_STOCK_CODE, report_type="balance")
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"eastmoney 资产负债表网络不可达: {exc}")

        assert isinstance(df, pd.DataFrame)


# ====================================================================
# Tushare — 可转债
# ====================================================================

class TestTushareCB:
    """tushare 可转债 — 需要 TUSHARE_TOKEN"""

    @pytest.mark.timeout(120)
    def test_query_cb_basic(self):
        from src.datacollect.collectors.tushare_collector import TushareCollector

        collector = TushareCollector()
        if not collector.available:
            pytest.skip("TUSHARE_TOKEN 未配置")
        try:
            df = collector.query_cb_basic()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"tushare 可转债网络不可达: {exc}")

        assert df is not None
        assert len(df) > 0, "tushare 可转债基础信息为空"

    @pytest.mark.timeout(120)
    def test_query_cb_daily(self):
        from src.datacollect.collectors.tushare_collector import TushareCollector

        collector = TushareCollector()
        if not collector.available:
            pytest.skip("TUSHARE_TOKEN 未配置")
        try:
            df = collector.query_cb_daily(trade_date="20250102")
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"tushare 可转债日线网络不可达: {exc}")

        assert df is not None


# ====================================================================
# AData — 可转债
# ====================================================================

class TestAdataCB:
    """adata 可转债列表"""

    @pytest.mark.timeout(120)
    def test_get_cb_list(self):
        from src.datacollect.collectors.adata_collector import AdataCollector

        collector = AdataCollector()
        try:
            df = collector.get_cb_list()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"adata 可转债网络不可达: {exc}")

        assert df is not None
        if hasattr(df, "__len__"):
            assert len(df) > 0, "adata 可转债列表为空"
