"""QMT E2E-X: 特色数据测试 (可转债 / ETF / IPO)

验证 xtdata 特色数据接口 (2023+ 新增):
  - download_cb_data / get_cb_info
  - download_etf_info / get_etf_info
  - get_ipo_info

运行: pytest tests/e2e/test_qmt_special.py -m qmt -v
"""
import pytest

pytestmark = pytest.mark.qmt


class TestConvertibleBond:
    """TC-X-01 ~ TC-X-03: 可转债数据"""

    def test_download_cb_data(self, qmt_client):
        """TC-X-01: 下载可转债基础信息不抛异常"""
        qmt_client.download_cb_data()

    def test_cb_sector_list(self, qmt_client):
        """TC-X-02: 沪深转债板块 >= 100 只"""
        codes = qmt_client.get_stock_list_in_sector("沪深转债")
        if not codes:
            codes = qmt_client.get_stock_list_in_sector("可转债")
        assert isinstance(codes, list)
        assert len(codes) >= 100, f"可转债仅 {len(codes)} 只"

    def test_get_cb_info(self, qmt_client):
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


class TestETFData:
    """TC-X-04 ~ TC-X-06: ETF 申赎清单"""

    def test_download_etf_info(self, qmt_client):
        """TC-X-04: 下载 ETF 申赎清单不抛异常"""
        qmt_client.download_etf_info()

    def test_get_etf_info(self, qmt_client):
        """TC-X-05: 获取 ETF 申赎清单返回 dict"""
        info = qmt_client.get_etf_info()
        assert isinstance(info, dict)

    def test_etf_sector_not_empty(self, qmt_client):
        """TC-X-06: ETF 板块列表有数据"""
        codes = qmt_client.get_stock_list_in_sector("沪深ETF")
        if not codes:
            codes = qmt_client.get_stock_list_in_sector("ETF")
        assert isinstance(codes, list)
        assert len(codes) > 50, f"ETF 仅 {len(codes)} 只"


class TestIPOData:
    """TC-X-07: 新股申购信息"""

    def test_get_ipo_info(self, qmt_client):
        """TC-X-07: get_ipo_info 返回 list (可能为空)"""
        info = qmt_client.get_ipo_info()
        assert isinstance(info, list)
