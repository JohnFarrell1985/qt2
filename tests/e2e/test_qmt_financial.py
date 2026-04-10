"""QMT E2E-F: 财务数据测试

验证从 QMT 下载与读取财务报表、每股指标数据。
基于 xtdata 文档: Balance / Income / CashFlow / Capital / Pershareindex 等表。

所有测试需要 QMT 完整数据服务 (需开启独立交易模式或使用极简版客户端)。

运行: pytest tests/e2e/test_qmt_financial.py -m qmt -v
"""
import pandas as pd
import pytest

pytestmark = [pytest.mark.qmt, pytest.mark.skip(reason="财务数据下载耗时过长, 暂时跳过")]

FINANCIAL_TABLES = [
    "Balance", "Income", "CashFlow", "Capital",
    "Holdernum", "Top10holder", "Top10flowholder", "Pershareindex",
]


class TestFinancialDownload:
    """TC-F-01 ~ TC-F-02: 财务数据下载 (需完整数据服务)"""

    def test_download_financial_data(self, qmt_client, require_full_data_service):
        """TC-F-01: download_financial_data 不抛异常"""
        qmt_client.download_financial_data(
            stock_list=["600519.SH"],
            table_list=["Balance", "Income"],
        )

    def test_download_financial_data2(self, qmt_client, require_full_data_service):
        """TC-F-02: download_financial_data2 批量下载"""
        qmt_client.download_financial_data2(
            stock_list=["600519.SH", "000001.SZ"],
            table_list=["Pershareindex"],
            start_time="20250401",
            end_time="20250410",
        )


class TestFinancialRead:
    """TC-F-03 ~ TC-F-06: 财务数据读取 (需完整数据服务)"""

    def test_balance_sheet(self, qmt_client, require_full_data_service):
        """TC-F-03: Balance 表返回 DataFrame, 包含 tot_assets"""
        raw = qmt_client.get_financial_data(
            stock_list=["600519.SH"],
            table_list=["Balance"],
            start_time="20250401",
            end_time="20250410",
        )
        assert isinstance(raw, dict)
        assert "Balance" in raw
        df = raw["Balance"]
        if isinstance(df, pd.DataFrame) and not df.empty:
            assert "tot_assets" in df.columns, f"Balance 缺少 tot_assets, 列: {list(df.columns)}"

    def test_income_statement(self, qmt_client, require_full_data_service):
        """TC-F-04: Income 表返回 DataFrame, 包含 revenue"""
        raw = qmt_client.get_financial_data(
            stock_list=["600519.SH"],
            table_list=["Income"],
            start_time="20250401",
            end_time="20250410",
        )
        assert "Income" in raw
        df = raw["Income"]
        if isinstance(df, pd.DataFrame) and not df.empty:
            assert "revenue" in df.columns

    def test_pershareindex(self, qmt_client, require_full_data_service):
        """TC-F-05: Pershareindex 表返回每股指标"""
        raw = qmt_client.get_financial_data(
            stock_list=["600519.SH"],
            table_list=["Pershareindex"],
            start_time="20250401",
            end_time="20250410",
        )
        assert "Pershareindex" in raw
        df = raw["Pershareindex"]
        if isinstance(df, pd.DataFrame) and not df.empty:
            assert "s_fa_eps_basic" in df.columns, (
                f"Pershareindex 缺少 s_fa_eps_basic, 列: {list(df.columns)}"
            )

    def test_multi_table_read(self, qmt_client, require_full_data_service):
        """TC-F-06: 同时获取多张表"""
        tables = ["Balance", "Income", "CashFlow"]
        raw = qmt_client.get_financial_data(
            stock_list=["600519.SH"],
            table_list=tables,
            start_time="20250401",
            end_time="20250410",
        )
        for t in tables:
            assert t in raw, f"缺少表: {t}"
