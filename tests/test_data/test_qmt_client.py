"""Tests for src/data/qmt_client.py"""
import sys
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_settings():
    with patch("src.data.qmt_client.settings") as m:
        m.qmt.mini_qmt_path = "/fake/qmt"
        yield m


@pytest.fixture
def mock_xtdata():
    """Create a mock xtquant.xtdata module."""
    mod = MagicMock()
    mod.get_sector_list.return_value = ["沪深A股", "创业板", "科创板"]
    mod.get_stock_list_in_sector.return_value = ["600519.SH", "000001.SZ"]
    mod.download_history_data.return_value = None
    mod.download_history_data2.return_value = None
    mod.download_history_contracts.return_value = None
    mod.get_market_data.return_value = {"open": MagicMock()}
    mod.get_market_data_ex.return_value = {"600519.SH": MagicMock()}
    mod.get_local_data.return_value = {"600519.SH": MagicMock()}
    mod.subscribe_quote.return_value = 1001
    mod.subscribe_whole_quote.return_value = 2001
    mod.unsubscribe_quote.return_value = None
    mod.get_full_tick.return_value = {"600519.SH": {"lastPrice": 1800.0}}
    mod.get_full_kline.return_value = {"close": MagicMock()}
    mod.get_financial_data.return_value = {"Balance": MagicMock()}
    mod.download_financial_data.return_value = None
    mod.download_financial_data2.return_value = None
    mod.get_instrument_detail.return_value = {"InstrumentName": "贵州茅台"}
    mod.get_instrument_type.return_value = {"stock": True, "index": False}
    mod.get_divid_factors.return_value = MagicMock()
    mod.get_trading_dates.return_value = [20240101, 20240102]
    mod.get_trading_calendar.return_value = ["20240102", "20240103"]
    mod.get_holidays.return_value = ["20240101"]
    mod.download_holiday_data.return_value = None
    mod.download_sector_data.return_value = None
    mod.download_index_weight.return_value = None
    mod.get_index_weight.return_value = {"600519.SH": 3.2}
    mod.get_period_list.return_value = ["1m", "5m", "1d"]
    mod.download_cb_data.return_value = None
    mod.get_cb_info.return_value = {"bondCode": "113009.SH"}
    mod.download_etf_info.return_value = None
    mod.get_etf_info.return_value = {"510300.SH": {}}
    mod.get_ipo_info.return_value = [{"securityCode": "301001.SZ"}]
    mod.reconnect.return_value = None
    mod.run.return_value = None
    return mod


@pytest.fixture
def client(mock_settings, mock_xtdata):
    modules = {
        "xtquant": MagicMock(),
        "xtquant.xtdata": mock_xtdata,
    }
    with patch.dict(sys.modules, modules):
        from src.data.qmt_client import QMTClient
        c = QMTClient()
        c._xtdata = mock_xtdata
        yield c


class TestXtdataProperty:

    def test_lazy_loads(self, mock_settings, mock_xtdata):
        modules = {
            "xtquant": MagicMock(),
            "xtquant.xtdata": mock_xtdata,
        }
        with patch.dict(sys.modules, modules):
            from src.data.qmt_client import QMTClient
            c = QMTClient()
            assert c._xtdata is None
            _ = c.xtdata
            assert c._xtdata is not None

    def test_import_error(self, mock_settings):
        from src.data.qmt_client import QMTClient
        c = QMTClient()
        with pytest.raises(ImportError, match="xtquant"):
            _ = c.xtdata


# ================================================================
# 行情接口
# ================================================================

class TestSubscribeQuote:

    def test_returns_seq(self, client, mock_xtdata):
        seq = client.subscribe_quote("600519.SH", period="tick")
        assert seq == 1001
        mock_xtdata.subscribe_quote.assert_called_once_with(
            "600519.SH", period="tick",
            start_time="", end_time="",
            count=0, callback=None,
        )


class TestSubscribeWholeQuote:

    def test_returns_seq(self, client, mock_xtdata):
        seq = client.subscribe_whole_quote(["SH", "SZ"])
        assert seq == 2001
        mock_xtdata.subscribe_whole_quote.assert_called_once_with(
            ["SH", "SZ"], callback=None,
        )


class TestUnsubscribeQuote:

    def test_calls_sdk(self, client, mock_xtdata):
        client.unsubscribe_quote(1001)
        mock_xtdata.unsubscribe_quote.assert_called_once_with(1001)


class TestGetMarketDataEx:

    def test_calls_sdk(self, client, mock_xtdata):
        result = client.get_market_data_ex(["600519.SH"], period="1d")
        assert "600519.SH" in result
        mock_xtdata.get_market_data_ex.assert_called_once()


class TestGetMarketData:

    def test_calls_old_api(self, client, mock_xtdata):
        client.get_market_data(["600519.SH"], period="1d")
        mock_xtdata.get_market_data.assert_called_once()


class TestGetLocalData:

    def test_calls_sdk(self, client, mock_xtdata):
        result = client.get_local_data(["600519.SH"])
        assert "600519.SH" in result
        mock_xtdata.get_local_data.assert_called_once()


class TestGetFullTick:

    def test_returns_dict(self, client, mock_xtdata):
        result = client.get_full_tick(["600519.SH"])
        assert "600519.SH" in result
        mock_xtdata.get_full_tick.assert_called_once_with(["600519.SH"])


class TestGetFullKline:

    def test_calls_sdk(self, client, mock_xtdata):
        client.get_full_kline(["600519.SH"], period="1m", count=5)
        mock_xtdata.get_full_kline.assert_called_once()


class TestGetDividFactors:

    def test_calls_sdk(self, client, mock_xtdata):
        client.get_divid_factors("600519.SH", start_time="20240101", end_time="20240601")
        mock_xtdata.get_divid_factors.assert_called_once_with(
            "600519.SH", "20240101", "20240601"
        )


class TestDownloadHistoryData:

    def test_single_stock(self, client, mock_xtdata):
        client.download_history_data("600519.SH", "1d", start_time="20240101")
        mock_xtdata.download_history_data.assert_called_once()


class TestDownloadHistoryData2:

    def test_batch(self, client, mock_xtdata):
        client.download_history_data2(
            stock_list=["600519.SH"],
            period="1d",
            start_time="20240101",
            end_time="20240601",
        )
        mock_xtdata.download_history_data2.assert_called_once_with(
            stock_list=["600519.SH"],
            period="1d",
            start_time="20240101",
            end_time="20240601",
            callback=None,
            incrementally=None,
        )


class TestDownloadHistoryContracts:

    def test_calls_sdk(self, client, mock_xtdata):
        client.download_history_contracts()
        mock_xtdata.download_history_contracts.assert_called_once()


# ================================================================
# 财务数据接口
# ================================================================

class TestGetFinancialData:

    def test_with_all_params(self, client, mock_xtdata):
        result = client.get_financial_data(
            stock_list=["600519.SH"],
            table_list=["Balance", "Income"],
            start_time="20230101",
            end_time="20231231",
        )
        assert "Balance" in result
        mock_xtdata.get_financial_data.assert_called_once_with(
            stock_list=["600519.SH"],
            table_list=["Balance", "Income"],
            start_time="20230101",
            end_time="20231231",
            report_type="announce_time",
        )


class TestDownloadFinancialData:

    def test_calls_sdk(self, client, mock_xtdata):
        client.download_financial_data(["600519.SH"], ["Balance"])
        mock_xtdata.download_financial_data.assert_called_once_with(
            ["600519.SH"], ["Balance"],
        )


class TestDownloadFinancialData2:

    def test_calls_sdk(self, client, mock_xtdata):
        client.download_financial_data2(
            ["600519.SH"], table_list=["Balance"],
            start_time="20230101", end_time="20231231",
        )
        mock_xtdata.download_financial_data2.assert_called_once()


# ================================================================
# 基础信息接口
# ================================================================

class TestGetInstrumentDetail:

    def test_returns_dict(self, client, mock_xtdata):
        result = client.get_instrument_detail("600519.SH")
        assert result["InstrumentName"] == "贵州茅台"

    def test_iscomplete_flag(self, client, mock_xtdata):
        client.get_instrument_detail("600519.SH", iscomplete=True)
        mock_xtdata.get_instrument_detail.assert_called_with("600519.SH", True)

    def test_returns_empty_on_none(self, client, mock_xtdata):
        mock_xtdata.get_instrument_detail.return_value = None
        assert client.get_instrument_detail("FAKE.XX") == {}


class TestGetInstrumentType:

    def test_returns_dict(self, client, mock_xtdata):
        result = client.get_instrument_type("600519.SH")
        assert result["stock"] is True


class TestGetSectorList:

    def test_returns_list(self, client, mock_xtdata):
        result = client.get_sector_list()
        assert result == ["沪深A股", "创业板", "科创板"]


class TestGetStockListInSector:

    def test_default_sector(self, client, mock_xtdata):
        result = client.get_stock_list_in_sector()
        assert "600519.SH" in result
        mock_xtdata.get_stock_list_in_sector.assert_called_with("沪深A股")

    def test_custom_sector(self, client, mock_xtdata):
        client.get_stock_list_in_sector("创业板")
        mock_xtdata.get_stock_list_in_sector.assert_called_with("创业板")


class TestDownloadSectorData:

    def test_calls_sdk(self, client, mock_xtdata):
        client.download_sector_data()
        mock_xtdata.download_sector_data.assert_called_once()


class TestGetIndexWeight:

    def test_returns_dict(self, client, mock_xtdata):
        result = client.get_index_weight("000300.SH")
        assert "600519.SH" in result


class TestDownloadIndexWeight:

    def test_calls_sdk(self, client, mock_xtdata):
        client.download_index_weight()
        mock_xtdata.download_index_weight.assert_called_once()


class TestGetTradingDates:

    def test_returns_list(self, client, mock_xtdata):
        result = client.get_trading_dates("SH")
        assert len(result) == 2


class TestGetTradingCalendar:

    def test_returns_list(self, client, mock_xtdata):
        result = client.get_trading_calendar("SH", "20240101", "20240131")
        assert len(result) == 2


class TestGetHolidays:

    def test_returns_list(self, client, mock_xtdata):
        result = client.get_holidays()
        assert "20240101" in result


class TestDownloadHolidayData:

    def test_calls_sdk(self, client, mock_xtdata):
        client.download_holiday_data()
        mock_xtdata.download_holiday_data.assert_called_once()


class TestGetPeriodList:

    def test_returns_list(self, client, mock_xtdata):
        result = client.get_period_list()
        assert "1d" in result


# ================================================================
# 特色数据
# ================================================================

class TestDownloadCbData:

    def test_calls_sdk(self, client, mock_xtdata):
        client.download_cb_data()
        mock_xtdata.download_cb_data.assert_called_once()


class TestGetCbInfo:

    def test_returns_dict(self, client, mock_xtdata):
        result = client.get_cb_info("113009.SH")
        assert "bondCode" in result


class TestDownloadEtfInfo:

    def test_calls_sdk(self, client, mock_xtdata):
        client.download_etf_info()
        mock_xtdata.download_etf_info.assert_called_once()


class TestGetEtfInfo:

    def test_returns_dict(self, client, mock_xtdata):
        result = client.get_etf_info()
        assert "510300.SH" in result


class TestGetIpoInfo:

    def test_returns_list(self, client, mock_xtdata):
        result = client.get_ipo_info("20230327", "20230327")
        assert len(result) == 1


# ================================================================
# 连接管理
# ================================================================

class TestReconnect:

    def test_with_ip_port(self, client, mock_xtdata):
        client.reconnect("127.0.0.1", 58610)
        mock_xtdata.reconnect.assert_called_once_with("127.0.0.1", 58610)

    def test_auto_reconnect(self, client, mock_xtdata):
        client.reconnect()
        mock_xtdata.reconnect.assert_called_once()


class TestRun:

    def test_calls_sdk(self, client, mock_xtdata):
        client.run()
        mock_xtdata.run.assert_called_once()
