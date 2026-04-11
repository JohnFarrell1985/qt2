"""E2E: 数据源可用性检查

原则: 任何数据源 2 分钟内无数据返回 = 完全不可用, 彻底放弃。
所有测试统一 @pytest.mark.timeout(120)。

注: FallbackDispatcher.check_availability() 是顺序检查所有源,
pytdx select_best_ip 扫描 40+ 服务器需 2min+, 故不在此测试。
各数据源已在此单独测试连通性。
"""
import pytest

from src.datacollect.rate_limiter import TokenBucketLimiter


@pytest.fixture(autouse=True)
def _reset_limiters():
    yield
    TokenBucketLimiter.reset_all()


class TestBaostockHealth:
    """baostock 连通性 — 免费无限流, 应当始终可用"""

    @pytest.mark.timeout(120)
    def test_login_logout(self):
        import baostock as bs
        lg = bs.login()
        assert lg.error_code == "0", f"baostock login failed: {lg.error_msg}"
        bs.logout()

    @pytest.mark.timeout(120)
    def test_collector_health_check(self):
        from src.datacollect.collectors.baostock_collector import BaostockCollector
        collector = BaostockCollector()
        assert collector.health_check() is True


class TestAkshareHealth:
    """akshare 连通性 — 已改用 stock_info_a_code_name 轻量接口 (~20s)"""

    @pytest.mark.timeout(120)
    def test_collector_health_check(self):
        from src.datacollect.collectors.akshare_collector import AkshareCollector
        collector = AkshareCollector()
        assert collector.health_check() is True


class TestTushareHealth:
    """tushare 连通性 — 取决于 TUSHARE_TOKEN 配置"""

    @pytest.mark.timeout(120)
    def test_token_check(self):
        from src.datacollect.collectors.tushare_collector import TushareCollector
        collector = TushareCollector()
        if not collector.available:
            pytest.skip("TUSHARE_TOKEN 未配置")
        assert collector.health_check() is True


class TestAdataHealth:
    """adata 连通性 — 底层走 East Money HTTP, 一般 30-90s"""

    @pytest.mark.timeout(120)
    def test_collector_health_check(self):
        from src.datacollect.collectors.adata_collector import AdataCollector
        collector = AdataCollector()
        assert collector.health_check() is True
