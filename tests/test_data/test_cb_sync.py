"""可转债数据采集 (CBDataSync) 单元测试"""
from datetime import date
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from src.data.cb_sync import CBDataSync, _clean_value, _to_float, _to_int


# ====================================================================
# 工具函数
# ====================================================================

class TestCleanValue:
    def test_normal(self):
        assert _clean_value("hello") == "hello"
        assert _clean_value(123) == 123

    def test_none(self):
        assert _clean_value(None) is None

    def test_nan(self):
        assert _clean_value(float("nan")) is None


class TestToFloat:
    def test_int(self):
        assert _to_float(10) == 10.0

    def test_str_number(self):
        assert _to_float("3.14") == pytest.approx(3.14)

    def test_none(self):
        assert _to_float(None) is None

    def test_nan(self):
        assert _to_float(float("nan")) is None

    def test_invalid(self):
        assert _to_float("abc") is None


class TestToInt:
    def test_float(self):
        assert _to_int(3.7) == 3

    def test_none(self):
        assert _to_int(None) is None

    def test_nan(self):
        assert _to_int(float("nan")) is None


# ====================================================================
# CBDataSync._map_cb_list
# ====================================================================

class TestMapCbList:
    def test_basic_mapping(self):
        df = pd.DataFrame({
            "转债代码": ["123001", "127001"],
            "转债名称": ["蓝标转债", "兴业转债"],
            "正股代码": ["300058", "601166"],
            "转股价": [10.5, 20.0],
            "评级": ["AA", "AAA"],
            "剩余规模": [5.0, 100.0],
        })
        rows = CBDataSync._map_cb_list(df)
        assert len(rows) == 2
        assert rows[0]["code"] == "123001"
        assert rows[0]["bond_name"] == "蓝标转债"
        assert rows[0]["convert_price"] == 10.5
        assert rows[1]["level"] == "AAA"

    def test_empty_df(self):
        df = pd.DataFrame()
        rows = CBDataSync._map_cb_list(df)
        assert rows == []

    def test_missing_code_column(self):
        df = pd.DataFrame({"名称": ["test"], "评级": ["AA"]})
        rows = CBDataSync._map_cb_list(df)
        assert rows == []

    def test_fallback_code_column(self):
        df = pd.DataFrame({
            "代码": ["128001"],
            "转债名称": ["测试转债"],
        })
        rows = CBDataSync._map_cb_list(df)
        assert len(rows) == 1
        assert rows[0]["code"] == "128001"


# ====================================================================
# CBDataSync._map_cb_daily
# ====================================================================

class TestMapCbDaily:
    def test_basic_mapping(self):
        df = pd.DataFrame({
            "date": ["2024-01-02", "2024-01-03"],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [10000, 20000],
        })
        rows = CBDataSync._map_cb_daily("123001.SZ", df, "20240101")
        assert len(rows) == 2
        assert rows[0]["code"] == "123001.SZ"
        assert rows[0]["trade_date"] == date(2024, 1, 2)
        assert rows[0]["open"] == 100.0
        assert rows[0]["volume"] == 10000

    def test_start_date_filter(self):
        df = pd.DataFrame({
            "date": ["2023-06-01", "2024-01-02"],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [10000, 20000],
        })
        rows = CBDataSync._map_cb_daily("123001", df, "20240101")
        assert len(rows) == 1
        assert rows[0]["trade_date"] == date(2024, 1, 2)

    def test_empty_df(self):
        df = pd.DataFrame({"date": [], "open": [], "high": [], "low": [], "close": [], "volume": []})
        rows = CBDataSync._map_cb_daily("123001", df, "20230101")
        assert rows == []


# ====================================================================
# sync_cb_list (集成 mock)
# ====================================================================

class TestSyncCbList:
    @patch("src.data.cb_sync.get_session")
    def test_success(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        df = pd.DataFrame({
            "转债代码": ["123001"],
            "转债名称": ["蓝标转债"],
            "正股代码": ["300058"],
            "转股价": [10.5],
            "评级": ["AA"],
            "剩余规模": [5.0],
        })
        mock_ak = MagicMock()
        mock_ak.bond_cb_jsl.return_value = df

        with patch("src.data.cb_sync._get_limiter") as mock_limiter_fn:
            mock_limiter_fn.return_value = MagicMock()
            with patch.dict("sys.modules", {"akshare": mock_ak}):
                sync = CBDataSync()
                count = sync.sync_cb_list()
                assert count == 1

    @patch("src.data.cb_sync._get_limiter")
    def test_api_error(self, mock_limiter_fn):
        mock_limiter_fn.return_value = MagicMock()
        mock_ak = MagicMock()
        mock_ak.bond_cb_jsl.side_effect = Exception("network error")

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            sync = CBDataSync()
            count = sync.sync_cb_list()
            assert count == 0


# ====================================================================
# sync_cb_daily (集成 mock)
# ====================================================================

class TestSyncCbDaily:
    @patch("src.data.cb_sync.get_session")
    def test_empty_table(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.query.return_value.all.return_value = []
        mock_get_session.return_value = mock_session

        mock_ak = MagicMock()
        with patch("src.data.cb_sync._get_limiter") as mock_limiter_fn:
            mock_limiter_fn.return_value = MagicMock()
            with patch.dict("sys.modules", {"akshare": mock_ak}):
                sync = CBDataSync()
                count = sync.sync_cb_daily()
                assert count == 0
