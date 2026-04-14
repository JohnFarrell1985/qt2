"""QMT E2E-X: 特色数据测试 (可转债 / ETF / IPO)

验证 xtdata 特色数据只读接口。
download 超时或券商不支持时自动 skip。

运行: pytest tests/e2e/qmt/test_qmt_special.py -m qmt -v
"""
import pytest

from tests.e2e.qmt.conftest import download_or_skip, skip_if_broker_error

pytestmark = pytest.mark.qmt


@pytest.mark.timeout(180)
class TestConvertibleBond:
    """TC-X-01 ~ TC-X-03: 可转债数据"""

    def test_download_cb_data(self, qmt_client, require_full_data_service):
        """TC-X-01: 下载可转债基础信息"""
        download_or_skip(qmt_client.download_cb_data, "download_cb_data")

    def test_cb_sector_list(self, qmt_client):
        """TC-X-02: 沪深转债板块 >= 100 只"""
        codes = qmt_client.get_stock_list_in_sector("沪深转债")
        if not codes:
            codes = qmt_client.get_stock_list_in_sector("可转债")
        assert isinstance(codes, list)
        assert len(codes) >= 100, f"可转债仅 {len(codes)} 只"

    def test_get_cb_info(self, qmt_client, require_full_data_service):
        """TC-X-03: 获取特定可转债信息"""
        codes = qmt_client.get_stock_list_in_sector("沪深转债")
        if not codes:
            codes = qmt_client.get_stock_list_in_sector("可转债")
        if not codes:
            pytest.skip("无可转债列表")

        info = qmt_client.get_cb_info(codes[0])
        assert isinstance(info, dict)
        if info:
            assert "bondName" in info or "underlyingCode" in info, (
                f"可转债信息缺少关键字段, keys={list(info.keys())}"
            )


@pytest.mark.timeout(180)
class TestETFData:
    """TC-X-04 ~ TC-X-06: ETF"""

    def test_download_etf_info(self, qmt_client, require_full_data_service):
        """TC-X-04: 下载 ETF 申赎清单"""
        download_or_skip(qmt_client.download_etf_info, "download_etf_info")

    def test_get_etf_info(self, qmt_client, require_full_data_service):
        """TC-X-05: 获取 ETF 申赎清单"""
        info = skip_if_broker_error(
            lambda: qmt_client.get_etf_info(),
            action_name="get_etf_info",
        )
        assert isinstance(info, dict)

    def test_etf_sector_not_empty(self, qmt_client):
        """TC-X-06: ETF 板块列表有数据"""
        codes = qmt_client.get_stock_list_in_sector("沪深ETF")
        if not codes:
            codes = qmt_client.get_stock_list_in_sector("ETF")
        assert isinstance(codes, list)
        assert len(codes) > 50, f"ETF 仅 {len(codes)} 只"


@pytest.mark.timeout(30)
class TestIPOData:
    """TC-X-07: 新股申购信息"""

    def test_get_ipo_info(self, qmt_client, require_full_data_service):
        """TC-X-07: get_ipo_info 返回 list"""
        info = skip_if_broker_error(
            lambda: qmt_client.get_ipo_info(),
            action_name="get_ipo_info",
        )
        assert isinstance(info, list)
