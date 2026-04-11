"""Tests for src/datacollect/collectors/baostock_collector.py"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.datacollect.base import CollectResult, CollectTask
from src.datacollect.collectors.baostock_collector import BaostockCollector


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture
def mock_limiter():
    limiter = MagicMock()
    limiter.acquire.return_value = True
    return limiter


def _make_result_data(rows: list[list], fields: list[str]):
    """构造模拟的 baostock ResultData 对象。"""
    rd = MagicMock()
    rd.error_code = "0"
    rd.error_msg = ""
    rd.fields = fields

    call_count = 0

    def _next():
        nonlocal call_count
        if call_count < len(rows):
            call_count += 1
            return True
        return False

    row_idx = {"i": -1}

    def _get_row_data():
        row_idx["i"] += 1
        return rows[row_idx["i"]]

    rd.next = _next
    rd.get_row_data = _get_row_data
    return rd


def _make_login_result(code: str = "0", msg: str = ""):
    lg = MagicMock()
    lg.error_code = code
    lg.error_msg = msg
    return lg


@pytest.fixture
def collector(mock_limiter):
    return BaostockCollector(limiter=mock_limiter)


# ====================================================================
# __init__
# ====================================================================

class TestInit:

    def test_custom_limiter(self, mock_limiter):
        c = BaostockCollector(limiter=mock_limiter)
        assert c.limiter is mock_limiter

    @patch("src.datacollect.collectors.baostock_collector.TokenBucketLimiter")
    def test_default_limiter(self, mock_tbl):
        mock_tbl.for_domain.return_value = MagicMock()
        c = BaostockCollector()
        mock_tbl.for_domain.assert_called_once()
        assert c.limiter is mock_tbl.for_domain.return_value

    def test_source_name(self, collector):
        assert collector.SOURCE == "baostock"

    def test_initially_not_logged_in(self, collector):
        assert collector._logged_in is False
        assert collector._bs is None


# ====================================================================
# _ensure_login
# ====================================================================

class TestEnsureLogin:

    @patch.dict("sys.modules", {"baostock": MagicMock()})
    def test_login_success(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")

        bs = collector._ensure_login()
        assert bs is mock_bs
        mock_bs.login.assert_called_once()
        assert collector._logged_in is True

    @patch.dict("sys.modules", {"baostock": MagicMock()})
    def test_login_failure_raises(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("1", "auth error")

        with pytest.raises(RuntimeError, match="login 失败"):
            collector._ensure_login()

    def test_import_error(self, collector):
        with patch.dict("sys.modules", {"baostock": None}):
            with pytest.raises((RuntimeError, ImportError)):
                collector._ensure_login()

    @patch.dict("sys.modules", {"baostock": MagicMock()})
    def test_reuses_session(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")

        collector._ensure_login()
        collector._ensure_login()
        mock_bs.login.assert_called_once()


# ====================================================================
# _to_dataframe
# ====================================================================

class TestToDataframe:

    def test_converts_rows(self):
        rows = [["2024-01-01", "sh.600000", "10.0"], ["2024-01-02", "sh.600000", "10.5"]]
        fields = ["date", "code", "open"]
        rs = _make_result_data(rows, fields)

        df = BaostockCollector._to_dataframe(rs)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert list(df.columns) == fields

    def test_empty_result(self):
        rs = _make_result_data([], ["date", "code"])
        df = BaostockCollector._to_dataframe(rs)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 0


# ====================================================================
# query_history_k_data
# ====================================================================

class TestQueryHistoryKData:

    @patch.dict("sys.modules", {"baostock": MagicMock(), "pandas": pd})
    def test_daily_kline(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")

        rows = [["2024-01-02", "sh.600000", "10", "11", "9", "10.5", "1000", "10000", "2", "1.5", "2.0"]]
        fields = ["date", "code", "open", "high", "low", "close", "volume", "amount", "adjustflag", "turn", "pctChg"]
        mock_bs.query_history_k_data_plus.return_value = _make_result_data(rows, fields)

        df = collector.query_history_k_data("sh.600000", "2024-01-01", "2024-01-03")
        assert len(df) == 1

    @patch.dict("sys.modules", {"baostock": MagicMock(), "pandas": pd})
    def test_minute_kline_no_turn_fields(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")

        rows = [["2024-01-02", "sh.600000", "10", "11", "9", "10.5", "1000", "10000", "2"]]
        fields = ["date", "code", "open", "high", "low", "close", "volume", "amount", "adjustflag"]
        mock_bs.query_history_k_data_plus.return_value = _make_result_data(rows, fields)

        df = collector.query_history_k_data("sh.600000", "2024-01-01", "2024-01-03", frequency="5")
        assert len(df) == 1

    @patch.dict("sys.modules", {"baostock": MagicMock(), "pandas": pd})
    def test_query_error_raises(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")

        err_rs = MagicMock()
        err_rs.error_code = "1"
        err_rs.error_msg = "query failed"
        mock_bs.query_history_k_data_plus.return_value = err_rs

        with pytest.raises(RuntimeError, match="query_history_k_data_plus 失败"):
            collector.query_history_k_data("sh.600000", "2024-01-01", "2024-01-03")

    def test_limiter_acquire_called(self, collector, mock_limiter):
        with patch.object(collector, "_ensure_login"):
            collector._bs = MagicMock()
            rs = _make_result_data([], ["date"])
            rs.error_code = "0"
            collector._bs.query_history_k_data_plus.return_value = rs

            collector.query_history_k_data("sh.600000", "2024-01-01", "2024-01-03")
            mock_limiter.acquire.assert_called_once()


# ====================================================================
# query_stock_basic / financial queries
# ====================================================================

class TestFinancialQueries:

    @patch.dict("sys.modules", {"baostock": MagicMock(), "pandas": pd})
    def test_query_stock_basic(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")
        mock_bs.query_stock_basic.return_value = _make_result_data(
            [["sh.600000", "浦发银行"]], ["code", "code_name"],
        )

        df = collector.query_stock_basic()
        assert len(df) == 1

    @patch.dict("sys.modules", {"baostock": MagicMock(), "pandas": pd})
    def test_query_profit_data(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")
        mock_bs.query_profit_data.return_value = _make_result_data(
            [["sh.600000", "0.15"]], ["code", "roeAvg"],
        )

        df = collector.query_profit_data("sh.600000", 2024, 1)
        assert len(df) == 1
        mock_bs.query_profit_data.assert_called_once_with(code="sh.600000", year=2024, quarter=1)

    @patch.dict("sys.modules", {"baostock": MagicMock(), "pandas": pd})
    def test_query_growth_data(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")
        mock_bs.query_growth_data.return_value = _make_result_data(
            [["sh.600000", "0.10"]], ["code", "YOYEquity"],
        )

        df = collector.query_growth_data("sh.600000", 2024, 2)
        assert len(df) == 1

    @patch.dict("sys.modules", {"baostock": MagicMock(), "pandas": pd})
    def test_query_balance_data(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")
        mock_bs.query_balance_data.return_value = _make_result_data(
            [["sh.600000", "0.55"]], ["code", "currentRatio"],
        )

        df = collector.query_balance_data("sh.600000", 2024, 3)
        assert len(df) == 1


# ====================================================================
# collect
# ====================================================================

class TestCollect:

    def test_missing_func_name(self, collector):
        task = CollectTask(params={})
        with pytest.raises(ValueError, match="func_name"):
            collector.collect(task)

    def test_unknown_func_name(self, collector):
        task = CollectTask(params={"func_name": "nonexistent"})
        with pytest.raises(AttributeError, match="没有公开方法"):
            collector.collect(task)

    def test_private_method_blocked(self, collector):
        task = CollectTask(params={"func_name": "_ensure_login"})
        with pytest.raises(AttributeError, match="没有公开方法"):
            collector.collect(task)

    def test_successful_collect(self, collector):
        fake_df = pd.DataFrame({"a": [1, 2, 3]})
        with patch.object(collector, "query_stock_basic", return_value=fake_df):
            task = CollectTask(
                source="baostock",
                params={"func_name": "query_stock_basic"},
            )
            result = collector.collect(task)

        assert isinstance(result, CollectResult)
        assert result.source == "baostock"
        assert result.metadata["records_count"] == 3
        assert result.metadata["func_name"] == "query_stock_basic"
        assert isinstance(result.collected_at, datetime)

    def test_collect_passes_params(self, collector):
        fake_df = pd.DataFrame()
        with patch.object(collector, "query_history_k_data", return_value=fake_df) as mock_fn:
            task = CollectTask(params={
                "func_name": "query_history_k_data",
                "code": "sh.600000",
                "start_date": "2024-01-01",
                "end_date": "2024-12-31",
            })
            collector.collect(task)
            mock_fn.assert_called_once_with(
                code="sh.600000",
                start_date="2024-01-01",
                end_date="2024-12-31",
            )


# ====================================================================
# health_check
# ====================================================================

class TestHealthCheck:

    def test_healthy(self, collector):
        with patch.object(collector, "_ensure_login"):
            assert collector.health_check() is True

    def test_unhealthy(self, collector):
        with patch.object(collector, "_ensure_login", side_effect=RuntimeError("fail")):
            assert collector.health_check() is False


# ====================================================================
# close / context manager
# ====================================================================

class TestCloseAndContextManager:

    @patch.dict("sys.modules", {"baostock": MagicMock()})
    def test_close_calls_logout(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")

        collector._ensure_login()
        collector.close()
        mock_bs.logout.assert_called_once()
        assert collector._logged_in is False

    def test_close_noop_when_not_logged_in(self, collector):
        collector.close()
        assert collector._logged_in is False

    @patch.dict("sys.modules", {"baostock": MagicMock()})
    def test_context_manager(self, mock_limiter):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")
        mock_bs.query_stock_basic.return_value = _make_result_data(
            [["sh.600000", "test"]], ["code", "name"],
        )

        with BaostockCollector(limiter=mock_limiter) as c:
            c.query_stock_basic()

        mock_bs.logout.assert_called_once()
