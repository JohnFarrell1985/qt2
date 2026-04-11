"""QMT E2E-X: 特色数据测试 (可转债 / ETF / IPO)

验证 xtdata 特色数据只读接口。
download_* 类接口在当前环境下可能长时间阻塞, 已标记 skip。

运行: pytest tests/e2e/test_qmt_special.py -m qmt -v
"""
import pytest

pytestmark = pytest.mark.qmt

SKIP_DOWNLOAD = pytest.mark.skip(reason="download_* 调用可能长时间阻塞, 暂时跳过")


@pytest.mark.timeout(15)
class TestConvertibleBond:
    """TC-X-01 ~ TC-X-03: 可转债数据"""

    @SKIP_DOWNLOAD
    def test_download_cb_data(self, qmt_client, require_full_data_service):
        """TC-X-01: 下载可转债基础信息不抛异常"""
        qmt_client.download_cb_data()

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


@pytest.mark.timeout(15)
class TestETFData:
    """TC-X-04 ~ TC-X-06: ETF"""

    @SKIP_DOWNLOAD
    def test_download_etf_info(self, qmt_client, require_broker_extended_api):
        """TC-X-04: 下载 ETF 申赎清单不抛异常"""
        qmt_client.download_etf_info()

    def test_get_etf_info(self, qmt_client, require_broker_extended_api):
        """TC-X-05: 获取 ETF 申赎清单返回 dict"""
        try:
            info = qmt_client.get_etf_info()
            assert isinstance(info, dict)
        except RuntimeError as e:
            if "300000" in str(e) or "not realize" in str(e):
                pytest.skip(f"券商限制: {e}")
            raise

    def test_etf_sector_not_empty(self, qmt_client):
        """TC-X-06: ETF 板块列表有数据"""
        codes = qmt_client.get_stock_list_in_sector("沪深ETF")
        if not codes:
            codes = qmt_client.get_stock_list_in_sector("ETF")
        assert isinstance(codes, list)
        assert len(codes) > 50, f"ETF 仅 {len(codes)} 只"


@pytest.mark.timeout(15)
class TestIPOData:
    """TC-X-07: 新股申购信息 (券商限制 API, 华泰不可用)"""

    def test_get_ipo_info(self, qmt_client, require_broker_extended_api):
        """TC-X-07: get_ipo_info 返回 list (可能为空)"""
        try:
            info = qmt_client.get_ipo_info()
            assert isinstance(info, list)
        except RuntimeError as e:
            if "200005" in str(e) or "300000" in str(e) or "not realize" in str(e):
                pytest.skip(f"券商限制: {e}")
            raise
