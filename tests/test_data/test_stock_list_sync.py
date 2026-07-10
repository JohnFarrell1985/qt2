"""Tests for src/data/stock_list_sync.py"""

import pandas as pd

from src.data.stock_list_sync import normalize_stock_code, records_from_dataframe


def test_normalize_stock_code():
    assert normalize_stock_code("600000") == "600000"
    assert normalize_stock_code("sh.600000") == "600000"
    assert normalize_stock_code("600000.SH") == "600000"
    assert normalize_stock_code("") is None


def test_records_from_baostock_df():
    df = pd.DataFrame([
        {"code": "sh.600000", "code_name": "浦发银行", "type": "1", "status": "1"},
        {"code": "sh.600001", "code_name": "旧股", "type": "1", "status": "0"},
        {"code": "sz.000001", "code_name": "平安银行", "type": "1", "status": "1"},
    ])
    rows = records_from_dataframe(df, "baostock")
    codes = {r["code"] for r in rows}
    assert codes == {"600000", "000001"}
    assert rows[0]["name"] == "浦发银行"


def test_records_from_eastmoney_df():
    df = pd.DataFrame([{"code": "300001", "name": "特锐德"}])
    rows = records_from_dataframe(df, "eastmoney")
    assert rows[0]["code"] == "300001"
    assert rows[0]["exchange"] == "SZ"
