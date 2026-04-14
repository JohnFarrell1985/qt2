"""QMT E2E-F: 财务数据测试

验证从 QMT 下载与读取财务报表、每股指标数据。
download 超时或券商不支持时自动 skip。

运行: pytest tests/e2e/qmt/test_qmt_financial.py -m qmt -v
"""
import pandas as pd
import pytest

from tests.e2e.qmt.conftest import download_or_skip

pytestmark = [pytest.mark.qmt, pytest.mark.timeout(180)]


def _extract_table(raw: dict, stock: str, table: str) -> pd.DataFrame | None:
    """从 get_financial_data 嵌套结构 {stock: {table: df}} 中提取"""
    return raw.get(stock, {}).get(table) if isinstance(raw, dict) else None


class TestFinancialDownload:
    """TC-F-01 ~ TC-F-02: 财务数据下载"""

    def test_download_financial_data(self, qmt_client, require_full_data_service):
        """TC-F-01: download_financial_data 不抛异常"""
        download_or_skip(
            lambda: qmt_client.download_financial_data(
                stock_list=["600519.SH"],
                table_list=["Balance", "Income"],
            ),
            action_name="download_financial_data",
        )

    def test_download_financial_data2(self, qmt_client, require_full_data_service):
        """TC-F-02: download_financial_data2 批量下载"""
        download_or_skip(
            lambda: qmt_client.download_financial_data2(
                stock_list=["600519.SH", "000001.SZ"],
                table_list=["Pershareindex"],
                start_time="20250401",
                end_time="20250410",
            ),
            action_name="download_financial_data2",
        )


class TestFinancialRead:
    """TC-F-03 ~ TC-F-06: 财务数据读取"""

    def test_balance_sheet(self, qmt_client, require_full_data_service):
        """TC-F-03: Balance 表返回 dict, 非空时包含 tot_assets"""
        raw = qmt_client.get_financial_data(
            stock_list=["600519.SH"],
            table_list=["Balance"],
            start_time="20250401",
            end_time="20250410",
        )
        assert isinstance(raw, dict)
        df = _extract_table(raw, "600519.SH", "Balance")
        assert df is not None, f"Balance 未返回, raw keys: {list(raw.keys())}"
        if not df.empty:
            assert "tot_assets" in df.columns, f"Balance 缺少 tot_assets, 列: {list(df.columns)}"

    def test_income_statement(self, qmt_client, require_full_data_service):
        """TC-F-04: Income 表返回 dict"""
        raw = qmt_client.get_financial_data(
            stock_list=["600519.SH"],
            table_list=["Income"],
            start_time="20250401",
            end_time="20250410",
        )
        df = _extract_table(raw, "600519.SH", "Income")
        assert df is not None
        if not df.empty:
            assert "revenue" in df.columns

    def test_pershareindex(self, qmt_client, require_full_data_service):
        """TC-F-05: Pershareindex 表返回每股指标"""
        raw = qmt_client.get_financial_data(
            stock_list=["600519.SH"],
            table_list=["Pershareindex"],
            start_time="20250401",
            end_time="20250410",
        )
        df = _extract_table(raw, "600519.SH", "Pershareindex")
        assert df is not None
        if not df.empty:
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
        assert isinstance(raw, dict)
        stock_data = raw.get("600519.SH", {})
        for t in tables:
            assert t in stock_data, f"缺少表: {t}, 可用: {list(stock_data.keys())}"
