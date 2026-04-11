"""QMT E2E-M: 行情数据测试

验证从 QMT 获取股票列表、合约信息、行情快照、除权因子等只读 API。
download_* 类接口在当前环境下可能长时间阻塞, 已标记 skip。

运行: pytest tests/e2e/test_qmt_market.py -m qmt -v
"""
import pandas as pd
import pytest

pytestmark = pytest.mark.qmt


@pytest.mark.timeout(15)
class TestStockList:
    """TC-M-01 ~ TC-M-03: 获取股票列表"""

    def test_a_share_list_not_empty(self, qmt_client):
        """TC-M-01: 沪深A股列表 > 4000 只"""
        codes = qmt_client.get_stock_list_in_sector("沪深A股")
        assert isinstance(codes, list)
        assert len(codes) > 4000, f"沪深A股仅 {len(codes)} 只, 预期 > 4000"

    def test_code_format(self, qmt_client):
        """TC-M-02: 代码格式 code.market (如 000001.SZ)"""
        codes = qmt_client.get_stock_list_in_sector("沪深A股")
        for code in codes[:20]:
            assert "." in code, f"代码缺少市场后缀: {code}"
            parts = code.split(".")
            assert len(parts) == 2
            assert parts[1] in ("SH", "SZ", "BJ"), f"未知市场: {parts[1]}"

    @pytest.mark.parametrize("sector", [
        "上证A股", "深证A股", "创业板", "科创板",
    ])
    def test_sub_sectors_not_empty(self, qmt_client, sector):
        """TC-M-03: 常见子板块均有成分股"""
        codes = qmt_client.get_stock_list_in_sector(sector)
        assert len(codes) > 0, f"板块 '{sector}' 为空"


@pytest.mark.timeout(15)
class TestInstrumentDetail:
    """TC-M-04 ~ TC-M-05: 合约基础信息"""

    @pytest.mark.parametrize("code", ["600519.SH", "000001.SZ", "300750.SZ"])
    def test_instrument_detail(self, qmt_client, require_full_data_service, code):
        """TC-M-04: get_instrument_detail 返回基础字段"""
        detail = qmt_client.get_instrument_detail(code)
        assert isinstance(detail, dict)
        assert detail, f"{code} 返回空 detail"
        assert "InstrumentName" in detail, f"{code} 缺少 InstrumentName"

    def test_instrument_type(self, qmt_client, require_full_data_service):
        """TC-M-05: get_instrument_type 返回类型标记"""
        result = qmt_client.get_instrument_type("600519.SH")
        assert isinstance(result, dict)
        assert result.get("stock") is True


@pytest.mark.timeout(15)
class TestMarketDataRead:
    """TC-M-06 ~ TC-M-07: 行情数据只读获取 (不含 download)"""

    def test_get_market_data_ex(self, qmt_client, require_full_data_service):
        """TC-M-06: get_market_data_ex 返回 dict[code, DataFrame]"""
        data = qmt_client.get_market_data_ex(
            ["600519.SH"], period="1d",
            start_time="20250401", end_time="20250410",
        )
        assert isinstance(data, dict)
        assert "600519.SH" in data
        df = data["600519.SH"]
        assert isinstance(df, pd.DataFrame)
        if len(df) > 0:
            for col in ["open", "high", "low", "close", "volume"]:
                assert col in df.columns, f"日线缺少字段: {col}"
            assert (df["close"] > 0).all(), "存在 close <= 0"
            assert (df["high"] >= df["low"]).all(), "存在 high < low"

    def test_get_local_data(self, qmt_client, require_full_data_service):
        """TC-M-07: get_local_data 读取本地缓存"""
        data = qmt_client.get_local_data(
            ["600519.SH"], period="1d",
            start_time="20250401", end_time="20250410",
        )
        assert isinstance(data, dict)
        if "600519.SH" in data:
            assert isinstance(data["600519.SH"], pd.DataFrame)


@pytest.mark.timeout(15)
class TestTickData:
    """TC-M-08 ~ TC-M-09: Tick / 除权因子"""

    def test_full_tick(self, qmt_client, require_full_data_service):
        """TC-M-08: get_full_tick 返回 dict 格式快照"""
        data = qmt_client.get_full_tick(["600519.SH", "000001.SZ"])
        assert isinstance(data, dict)

    def test_divid_factors(self, qmt_client):
        """TC-M-09: 除权因子数据 (两种模式都可用)"""
        result = qmt_client.get_divid_factors(
            "600519.SH", start_time="20250401", end_time="20250410",
        )
        assert result is not None


@pytest.mark.timeout(30)
class TestDailyKlineDownload:
    """TC-M-10 ~ TC-M-12: 日线下载+验证"""

    def test_download_and_get_daily(self, qmt_client, require_full_data_service):
        """TC-M-10: download_history_data + get_market_data_ex"""
        qmt_client.download_history_data(
            "600519.SH", period="1d",
            start_time="20250401", end_time="20250410",
        )
        data = qmt_client.get_market_data_ex(
            ["600519.SH"], period="1d",
            start_time="20250401", end_time="20250410",
        )
        df = data["600519.SH"]
        assert len(df) > 0, "下载后日线数据为空"
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in df.columns, f"日线缺少字段: {col}"

    def test_daily_values_sane(self, qmt_client, require_full_data_service):
        """TC-M-11: 日线数值合理性"""
        data = qmt_client.get_market_data_ex(
            ["600519.SH"], period="1d",
            start_time="20250401", end_time="20250410",
        )
        df = data["600519.SH"]
        if len(df) > 0:
            assert (df["close"] > 0).all(), "存在 close <= 0"
            assert (df["high"] >= df["low"]).all(), "存在 high < low"

    def test_batch_download(self, qmt_client, require_full_data_service, sample_stock_list):
        """TC-M-12: download_history_data2 批量下载"""
        qmt_client.download_history_data2(
            sample_stock_list, period="1d",
            start_time="20250401", end_time="20250410",
        )
        data = qmt_client.get_market_data_ex(
            sample_stock_list, period="1d",
            start_time="20250401", end_time="20250410",
        )
        for code in sample_stock_list:
            assert code in data, f"{code} 未返回数据"


@pytest.mark.timeout(30)
class TestMinuteKlineDownload:
    """TC-M-13 ~ TC-M-14: 分钟线下载"""

    def test_5min_data(self, qmt_client, require_full_data_service):
        """TC-M-13: 5分钟线下载+获取"""
        code = "600519.SH"
        qmt_client.download_history_data(
            code, period="5m",
            start_time="20250401", end_time="20250402",
        )
        data = qmt_client.get_market_data_ex(
            [code], period="5m",
            start_time="20250401", end_time="20250402",
        )
        assert code in data

    def test_1min_data(self, qmt_client, require_full_data_service):
        """TC-M-14: 1分钟线下载 (限1天)"""
        code = "000001.SZ"
        qmt_client.download_history_data(
            code, period="1m",
            start_time="20250401", end_time="20250401",
        )
        data = qmt_client.get_market_data_ex(
            [code], period="1m",
            start_time="20250401", end_time="20250401",
        )
        assert code in data
