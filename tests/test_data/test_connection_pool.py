"""Tests for A35 connection reuse in BaostockCollector and PytdxCollector."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.datacollect.collectors.baostock_collector import BaostockCollector
from src.datacollect.collectors.pytdx_collector import (
    MARKET_SH,
    PytdxCollector,
)


# ====================================================================
# Shared helpers
# ====================================================================

def _make_login_result(code: str = "0", msg: str = ""):
    lg = MagicMock()
    lg.error_code = code
    lg.error_msg = msg
    return lg


def _make_result_data(rows: list[list], fields: list[str]):
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


@pytest.fixture
def mock_limiter():
    limiter = MagicMock()
    limiter.acquire.return_value = True
    return limiter


# ####################################################################
# BaostockCollector — connection reuse
# ####################################################################

class TestBaostockConnectionReuse:

    @pytest.fixture
    def collector(self, mock_limiter):
        return BaostockCollector(limiter=mock_limiter)

    @patch.dict("sys.modules", {"baostock": MagicMock()})
    def test_login_called_only_once(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")
        mock_bs.query_stock_basic.return_value = _make_result_data(
            [["sh.600000", "浦发银行"]], ["code", "code_name"],
        )

        collector.query_stock_basic()
        collector.query_stock_basic()

        mock_bs.login.assert_called_once()

    @patch.dict("sys.modules", {"baostock": MagicMock()})
    def test_no_logout_between_queries(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")
        mock_bs.query_stock_basic.return_value = _make_result_data(
            [["sh.600000", "test"]], ["code", "name"],
        )

        collector.query_stock_basic()
        collector.query_stock_basic()

        mock_bs.logout.assert_not_called()

    @patch.dict("sys.modules", {"baostock": MagicMock()})
    def test_close_calls_logout(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")
        mock_bs.query_stock_basic.return_value = _make_result_data([], ["code"])

        collector.query_stock_basic()
        collector.close()

        mock_bs.logout.assert_called_once()

    @patch.dict("sys.modules", {"baostock": MagicMock()})
    def test_close_resets_state(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")
        mock_bs.query_stock_basic.return_value = _make_result_data([], ["code"])

        collector.query_stock_basic()
        assert collector._logged_in is True
        collector.close()
        assert collector._logged_in is False
        assert collector._bs is None

    @patch.dict("sys.modules", {"baostock": MagicMock()})
    def test_close_idempotent(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")
        mock_bs.query_stock_basic.return_value = _make_result_data([], ["code"])

        collector.query_stock_basic()
        collector.close()
        collector.close()

        mock_bs.logout.assert_called_once()

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
            c.query_stock_basic()

        mock_bs.login.assert_called_once()
        mock_bs.logout.assert_called_once()

    @patch.dict("sys.modules", {"baostock": MagicMock()})
    def test_reconnect_on_failure(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")

        call_count = {"n": 0}

        def _query_basic_side_effect():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ConnectionError("connection lost")
            return _make_result_data([["sh.600000", "ok"]], ["code", "name"])

        mock_bs.query_stock_basic.side_effect = _query_basic_side_effect

        df = collector.query_stock_basic()
        assert len(df) == 1
        assert mock_bs.login.call_count == 2

    @patch.dict("sys.modules", {"baostock": MagicMock()})
    def test_query_after_close_relogins(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")
        mock_bs.query_stock_basic.return_value = _make_result_data([], ["code"])

        collector.query_stock_basic()
        collector.close()
        collector.query_stock_basic()

        assert mock_bs.login.call_count == 2


class TestBaostockHealthCheck:

    @pytest.fixture
    def collector(self, mock_limiter):
        return BaostockCollector(limiter=mock_limiter)

    @patch.dict("sys.modules", {"baostock": MagicMock()})
    def test_healthy_reuses_connection(self, collector):
        import sys
        mock_bs = sys.modules["baostock"]
        mock_bs.login.return_value = _make_login_result("0")

        assert collector.health_check() is True
        mock_bs.logout.assert_not_called()

    def test_unhealthy(self, collector):
        with patch.object(collector, "_ensure_login", side_effect=RuntimeError("fail")):
            assert collector.health_check() is False


# ####################################################################
# PytdxCollector — connection reuse
# ####################################################################

class TestPytdxConnectionReuse:

    @pytest.fixture
    def mock_api(self):
        api = MagicMock()
        api.connect.return_value = api
        api.disconnect.return_value = None
        return api

    @pytest.fixture
    def mock_best_ip(self):
        return {"ip": "119.147.212.81", "port": 7709}

    @pytest.fixture
    def collector(self, mock_limiter):
        return PytdxCollector(limiter=mock_limiter)

    def test_connect_called_only_once(self, collector, mock_api, mock_best_ip):
        collector._best_ip = mock_best_ip
        fake_df = pd.DataFrame({"open": [10.0], "close": [10.5]})
        mock_api.get_security_bars.return_value = fake_df

        with patch.dict("sys.modules", {"pytdx": MagicMock(), "pytdx.hq": MagicMock()}):
            import sys
            sys.modules["pytdx.hq"].TdxHq_API = MagicMock(return_value=mock_api)

            collector.get_security_bars("600000", MARKET_SH, category=9, count=100)
            collector.get_security_bars("600000", MARKET_SH, category=9, count=100)

            mock_api.connect.assert_called_once()

    def test_no_disconnect_between_queries(self, collector, mock_api, mock_best_ip):
        collector._best_ip = mock_best_ip
        fake_df = pd.DataFrame({"open": [10.0]})
        mock_api.get_security_bars.return_value = fake_df

        with patch.dict("sys.modules", {"pytdx": MagicMock(), "pytdx.hq": MagicMock()}):
            import sys
            sys.modules["pytdx.hq"].TdxHq_API = MagicMock(return_value=mock_api)

            collector.get_security_bars("600000", MARKET_SH)
            collector.get_security_bars("600000", MARKET_SH)

            mock_api.disconnect.assert_not_called()

    def test_close_calls_disconnect(self, collector, mock_api, mock_best_ip):
        collector._best_ip = mock_best_ip
        fake_df = pd.DataFrame({"open": [10.0]})
        mock_api.get_security_bars.return_value = fake_df

        with patch.dict("sys.modules", {"pytdx": MagicMock(), "pytdx.hq": MagicMock()}):
            import sys
            sys.modules["pytdx.hq"].TdxHq_API = MagicMock(return_value=mock_api)

            collector.get_security_bars("600000", MARKET_SH)
            collector.close()

            mock_api.disconnect.assert_called_once()

    def test_close_resets_state(self, collector, mock_api, mock_best_ip):
        collector._best_ip = mock_best_ip
        fake_df = pd.DataFrame({"a": [1]})
        mock_api.get_security_bars.return_value = fake_df

        with patch.dict("sys.modules", {"pytdx": MagicMock(), "pytdx.hq": MagicMock()}):
            import sys
            sys.modules["pytdx.hq"].TdxHq_API = MagicMock(return_value=mock_api)

            collector.get_security_bars("600000", MARKET_SH)
            assert collector._connected is True
            collector.close()
            assert collector._connected is False
            assert collector._api is None

    def test_close_idempotent(self, collector, mock_api, mock_best_ip):
        collector._best_ip = mock_best_ip
        fake_df = pd.DataFrame({"a": [1]})
        mock_api.get_security_bars.return_value = fake_df

        with patch.dict("sys.modules", {"pytdx": MagicMock(), "pytdx.hq": MagicMock()}):
            import sys
            sys.modules["pytdx.hq"].TdxHq_API = MagicMock(return_value=mock_api)

            collector.get_security_bars("600000", MARKET_SH)
            collector.close()
            collector.close()

            mock_api.disconnect.assert_called_once()

    def test_context_manager(self, mock_limiter, mock_api, mock_best_ip):
        fake_df = pd.DataFrame({"a": [1]})
        mock_api.get_security_bars.return_value = fake_df

        with patch.dict("sys.modules", {"pytdx": MagicMock(), "pytdx.hq": MagicMock()}):
            import sys
            sys.modules["pytdx.hq"].TdxHq_API = MagicMock(return_value=mock_api)

            with PytdxCollector(limiter=mock_limiter) as c:
                c._best_ip = mock_best_ip
                c.get_security_bars("600000", MARKET_SH)
                c.get_security_bars("600000", MARKET_SH)

            mock_api.connect.assert_called_once()
            mock_api.disconnect.assert_called_once()

    def test_reconnect_on_failure(self, collector, mock_best_ip):
        collector._best_ip = mock_best_ip

        mock_api = MagicMock()
        mock_api.connect.return_value = mock_api
        mock_api.disconnect.return_value = None

        call_count = {"n": 0}
        fake_df = pd.DataFrame({"open": [10.0]})

        def _bars_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ConnectionError("link broken")
            return fake_df

        mock_api.get_security_bars.side_effect = _bars_side_effect

        with patch.dict("sys.modules", {"pytdx": MagicMock(), "pytdx.hq": MagicMock()}):
            import sys
            sys.modules["pytdx.hq"].TdxHq_API = MagicMock(return_value=mock_api)

            df = collector.get_security_bars("600000", MARKET_SH)
            assert len(df) == 1
            assert mock_api.connect.call_count == 2

    def test_query_after_close_reconnects(self, collector, mock_api, mock_best_ip):
        collector._best_ip = mock_best_ip
        fake_df = pd.DataFrame({"a": [1]})
        mock_api.get_security_bars.return_value = fake_df

        with patch.dict("sys.modules", {"pytdx": MagicMock(), "pytdx.hq": MagicMock()}):
            import sys
            mock_cls = MagicMock(return_value=mock_api)
            sys.modules["pytdx.hq"].TdxHq_API = mock_cls

            collector.get_security_bars("600000", MARKET_SH)
            collector.close()
            collector.get_security_bars("600000", MARKET_SH)

            assert mock_api.connect.call_count == 2


class TestPytdxHealthCheck:

    @pytest.fixture
    def collector(self, mock_limiter):
        return PytdxCollector(limiter=mock_limiter)

    def test_healthy_reuses_connection(self, collector):
        mock_api = MagicMock()
        mock_api.connect.return_value = mock_api
        with patch.object(collector, "_ensure_connected", return_value=mock_api):
            assert collector.health_check() is True
            mock_api.disconnect.assert_not_called()

    def test_unhealthy(self, collector):
        with patch.object(collector, "_ensure_connected", side_effect=RuntimeError("no server")):
            assert collector.health_check() is False
