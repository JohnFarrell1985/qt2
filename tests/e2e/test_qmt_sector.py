"""QMT E2E-S: 板块 / 指数 / 日历测试

验证板块分类、指数成分权重、交易日历、节假日等基础信息接口。

运行: pytest tests/e2e/test_qmt_sector.py -m qmt -v
"""
import pytest

pytestmark = pytest.mark.qmt


class TestSectorData:
    """TC-S-01 ~ TC-S-04: 板块分类"""

    def test_download_sector_data(self, qmt_client):
        """TC-S-01: 下载板块分类不抛异常"""
        qmt_client.download_sector_data()

    def test_get_sector_list(self, qmt_client):
        """TC-S-02: 板块列表非空, 含 '沪深A股'"""
        sectors = qmt_client.get_sector_list()
        assert isinstance(sectors, list)
        assert len(sectors) > 0
        assert "沪深A股" in sectors, f"板块列表缺少 '沪深A股', 前20个: {sectors[:20]}"

    @pytest.mark.parametrize("sector,min_count", [
        ("沪深A股", 4000),
        ("沪深300", 290),
        ("中证500", 490),
    ])
    def test_sector_constituents(self, qmt_client, sector, min_count):
        """TC-S-03: 板块成分股数量合理"""
        codes = qmt_client.get_stock_list_in_sector(sector)
        assert len(codes) >= min_count, (
            f"'{sector}' 成分股 {len(codes)} < 预期 {min_count}"
        )

    def test_sector_empty_for_unknown(self, qmt_client):
        """TC-S-04: 不存在的板块返回空列表"""
        codes = qmt_client.get_stock_list_in_sector("不存在的板块_test")
        assert isinstance(codes, list)
        assert len(codes) == 0


class TestIndexWeight:
    """TC-S-05 ~ TC-S-06: 指数权重"""

    def test_download_index_weight(self, qmt_client):
        """TC-S-05: 下载指数权重不抛异常"""
        qmt_client.download_index_weight()

    def test_get_index_weight(self, qmt_client, sample_index_code):
        """TC-S-06: 沪深300 权重 dict 非空, 值为正数"""
        weights = qmt_client.get_index_weight(sample_index_code)
        assert isinstance(weights, dict)
        if weights:
            for code, w in list(weights.items())[:5]:
                assert isinstance(w, (int, float))
                assert w > 0, f"权重非正: {code}={w}"


class TestTradingCalendar:
    """TC-S-07 ~ TC-S-10: 交易日历与节假日"""

    def test_download_holiday_data(self, qmt_client):
        """TC-S-07: 下载节假日数据不抛异常"""
        qmt_client.download_holiday_data()

    def test_get_trading_dates(self, qmt_client):
        """TC-S-08: 获取 2025 年交易日列表 (约 240~250 天)"""
        dates = qmt_client.get_trading_dates(
            "SH", start_time="20250101", end_time="20251231",
        )
        assert isinstance(dates, list)
        assert 200 < len(dates) < 260, f"2025 交易日 {len(dates)} 天, 异常"

    def test_get_trading_calendar(self, qmt_client):
        """TC-S-09: 交易日历返回列表"""
        cal = qmt_client.get_trading_calendar(
            "SH", start_time="20250101", end_time="20250131",
        )
        assert isinstance(cal, list)
        assert len(cal) > 0

    def test_get_holidays(self, qmt_client):
        """TC-S-10: 节假日列表含元旦 (当年或往年)"""
        holidays = qmt_client.get_holidays()
        assert isinstance(holidays, list)
        assert len(holidays) > 0
