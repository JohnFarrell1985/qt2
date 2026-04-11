"""QMT E2E-S: 板块 / 指数 / 日历测试

验证板块分类、指数成分等只读 API。
download_* 类接口在当前环境下可能长时间阻塞, 已标记 skip。

运行: pytest tests/e2e/test_qmt_sector.py -m qmt -v
"""
import pytest

pytestmark = pytest.mark.qmt

SKIP_DOWNLOAD = pytest.mark.skip(reason="download_* 调用可能长时间阻塞, 暂时跳过")


@pytest.mark.timeout(15)
class TestSectorRead:
    """TC-S-01 ~ TC-S-04: 板块只读查询"""

    def test_get_sector_list(self, qmt_client, require_full_data_service):
        """TC-S-01: 板块列表非空, 含 '沪深A股'"""
        sectors = qmt_client.get_sector_list()
        assert isinstance(sectors, list)
        assert len(sectors) > 0
        assert "沪深A股" in sectors, f"板块列表缺少 '沪深A股', 前20个: {sectors[:20]}"

    def test_a_share_constituents(self, qmt_client):
        """TC-S-02: 沪深A股成分股 > 4000 (主客户端可用)"""
        codes = qmt_client.get_stock_list_in_sector("沪深A股")
        assert len(codes) >= 4000, f"'沪深A股' 成分股 {len(codes)} < 预期 4000"

    @pytest.mark.parametrize("sector,min_count", [
        ("沪深300", 290),
        ("中证500", 490),
    ])
    def test_index_constituents(self, qmt_client, require_full_data_service, sector, min_count):
        """TC-S-03: 指数成分股数量合理"""
        codes = qmt_client.get_stock_list_in_sector(sector)
        assert len(codes) >= min_count, (
            f"'{sector}' 成分股 {len(codes)} < 预期 {min_count}"
        )

    def test_sector_empty_for_unknown(self, qmt_client):
        """TC-S-04: 不存在的板块返回空列表"""
        codes = qmt_client.get_stock_list_in_sector("不存在的板块_test")
        assert isinstance(codes, list)
        assert len(codes) == 0


@SKIP_DOWNLOAD
@pytest.mark.timeout(30)
class TestSectorDownload:
    """TC-S-05: 板块下载 (download_* 阻塞, 暂跳过)"""

    def test_download_sector_data(self, qmt_client, require_full_data_service):
        """TC-S-05: 下载板块分类不抛异常"""
        qmt_client.download_sector_data()


@pytest.mark.timeout(15)
class TestIndexWeight:
    """TC-S-06 ~ TC-S-07: 指数权重 (券商限制 API, 华泰不可用)"""

    @SKIP_DOWNLOAD
    def test_download_index_weight(self, qmt_client, require_broker_extended_api):
        """TC-S-06: 下载指数权重不抛异常"""
        qmt_client.download_index_weight()

    def test_get_index_weight(self, qmt_client, require_broker_extended_api, sample_index_code):
        """TC-S-07: 沪深300 权重 dict, 值为正数"""
        weights = qmt_client.get_index_weight(sample_index_code)
        assert isinstance(weights, dict)
        if weights:
            for code, w in list(weights.items())[:5]:
                assert isinstance(w, (int, float))
                assert w > 0, f"权重非正: {code}={w}"


@pytest.mark.timeout(15)
class TestTradingCalendar:
    """TC-S-08 ~ TC-S-11: 交易日历与节假日 (券商限制 API, 华泰不可用)"""

    @SKIP_DOWNLOAD
    def test_download_holiday_data(self, qmt_client, require_broker_extended_api):
        """TC-S-08: 下载节假日数据不抛异常"""
        qmt_client.download_holiday_data()

    def test_get_trading_dates(self, qmt_client, require_broker_extended_api):
        """TC-S-09: 获取 2025 年交易日列表 (约 240~250 天)"""
        dates = qmt_client.get_trading_dates(
            "SH", start_time="20250101", end_time="20251231",
        )
        assert isinstance(dates, list)
        assert 200 < len(dates) < 260, f"2025 交易日 {len(dates)} 天, 异常"

    def test_get_trading_calendar(self, qmt_client, require_broker_extended_api):
        """TC-S-10: 交易日历返回列表"""
        try:
            cal = qmt_client.get_trading_calendar(
                "SH", start_time="20250101", end_time="20250131",
            )
            assert isinstance(cal, list)
            assert len(cal) > 0
        except RuntimeError as e:
            if "300000" in str(e) or "not realize" in str(e):
                pytest.skip(f"券商限制: {e}")
            raise

    def test_get_holidays(self, qmt_client, require_broker_extended_api):
        """TC-S-11: 节假日列表非空"""
        holidays = qmt_client.get_holidays()
        assert isinstance(holidays, list)
        if len(holidays) == 0:
            pytest.skip("get_holidays 返回空列表, 可能需先 download_holiday_data")
