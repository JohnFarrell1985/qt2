"""E2E: Tier 2 全球情报信号采集 — yfinance / 新浪全球

原则: 2 分钟内无数据返回 = 数据源不可用, 彻底放弃。

这些数据不是交易标的, 而是 A 股盘前情报信号:
- 全球指数 (SPX, NASDAQ, DJI, HSI, NIKKEI, FTSE, DAX)
- VIX 恐慌指数
- 黄金 XAUUSD, 原油 WTI/BRENT
- 外汇 USDCNY
- 国债收益率 US10Y
- 富时 A50

验证: 数据源可达, 返回非空, 字段合理。不落盘。
"""
import time
import pytest

from src.datacollect.rate_limiter import TokenBucketLimiter

_NETWORK_ERRORS = (ConnectionError, OSError, RuntimeError, ImportError)

YFINANCE_PAUSE = 8


@pytest.fixture(autouse=True)
def _reset_limiters():
    yield
    TokenBucketLimiter.reset_all()


def _skip_on_rate_limit(rows, msg):
    """yfinance 频繁请求触发限流时 skip, 不标记为 FAIL."""
    if not rows:
        pytest.skip(f"yfinance 限流或无数据: {msg}")


# ====================================================================
# Yahoo Finance (yfinance) — Tier 2 主力源
#
# yfinance 对连续请求非常敏感, 每个测试类之间休眠 YFINANCE_PAUSE 秒
# ====================================================================

class TestYfinanceGlobalIndex:
    """yfinance 全球指数采集"""

    @pytest.mark.timeout(120)
    def test_fetch_global_index(self):
        from src.datacollect.collectors.yfinance_collector import YfinanceCollector

        collector = YfinanceCollector()
        try:
            rows = collector.fetch_global_index()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"yfinance 全球指数网络不可达: {exc}")

        _skip_on_rate_limit(rows, "global_index")
        symbols = [r["symbol"] for r in rows]
        assert any(s in symbols for s in ("SPX", "NASDAQ", "DJI")), (
            f"缺少核心美股指数, 实际返回: {symbols}"
        )
        for row in rows:
            assert "close_price" in row
            assert row["close_price"] is None or row["close_price"] > 0

        time.sleep(YFINANCE_PAUSE)


class TestYfinanceVIX:
    """yfinance VIX 恐慌指数"""

    @pytest.mark.timeout(120)
    def test_fetch_vix(self):
        from src.datacollect.collectors.yfinance_collector import YfinanceCollector

        collector = YfinanceCollector()
        try:
            rows = collector.fetch_vix()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"yfinance VIX 网络不可达: {exc}")

        _skip_on_rate_limit(rows, "vix")
        vix = rows[0]
        assert vix["symbol"] == "VIX"
        assert vix["close_price"] is not None
        assert 5 < vix["close_price"] < 100, (
            f"VIX 值异常: {vix['close_price']} (正常范围 10-40)"
        )

        time.sleep(YFINANCE_PAUSE)


class TestYfinanceCommodities:
    """yfinance 黄金 + 原油"""

    @pytest.mark.timeout(120)
    def test_fetch_gold(self):
        from src.datacollect.collectors.yfinance_collector import YfinanceCollector

        collector = YfinanceCollector()
        try:
            rows = collector.fetch_gold()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"yfinance 黄金网络不可达: {exc}")

        _skip_on_rate_limit(rows, "gold")
        gold = rows[0]
        assert gold["close_price"] is not None
        assert gold["close_price"] > 500, (
            f"黄金价格异常: {gold['close_price']} (应 > 500 USD/oz)"
        )

        time.sleep(YFINANCE_PAUSE)

    @pytest.mark.timeout(120)
    def test_fetch_crude_oil(self):
        from src.datacollect.collectors.yfinance_collector import YfinanceCollector

        collector = YfinanceCollector()
        try:
            rows = collector.fetch_crude_oil()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"yfinance 原油网络不可达: {exc}")

        _skip_on_rate_limit(rows, "crude_oil")
        for row in rows:
            assert row["close_price"] is None or row["close_price"] > 10

        time.sleep(YFINANCE_PAUSE)


class TestYfinanceForex:
    """yfinance 外汇 USDCNY"""

    @pytest.mark.timeout(120)
    def test_fetch_forex(self):
        from src.datacollect.collectors.yfinance_collector import YfinanceCollector

        collector = YfinanceCollector()
        try:
            rows = collector.fetch_forex()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"yfinance 外汇网络不可达: {exc}")

        _skip_on_rate_limit(rows, "forex")
        usdcny = [r for r in rows if r["symbol"] == "USDCNY"]
        if usdcny:
            rate = usdcny[0]["close_price"]
            assert rate is not None
            assert 5.0 < rate < 10.0, (
                f"USDCNY 汇率异常: {rate} (正常范围 6.5-7.5)"
            )

        time.sleep(YFINANCE_PAUSE)


class TestYfinanceBondYield:
    """yfinance 国债收益率"""

    @pytest.mark.timeout(120)
    def test_fetch_bond_yield(self):
        from src.datacollect.collectors.yfinance_collector import YfinanceCollector

        collector = YfinanceCollector()
        try:
            rows = collector.fetch_bond_yield()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"yfinance 国债网络不可达: {exc}")

        _skip_on_rate_limit(rows, "bond_yield")

        time.sleep(YFINANCE_PAUSE)


class TestYfinanceFTSEA50:
    """yfinance 富时中国 A50"""

    @pytest.mark.timeout(120)
    def test_fetch_ftse_a50(self):
        from src.datacollect.collectors.yfinance_collector import YfinanceCollector

        collector = YfinanceCollector()
        try:
            rows = collector.fetch_ftse_a50()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"yfinance 富时 A50 网络不可达: {exc}")

        assert isinstance(rows, list)
        if rows:
            assert rows[0]["symbol"] == "FTSE_A50"

        time.sleep(YFINANCE_PAUSE)


class TestYfinanceCollect:
    """yfinance collect() 统一接口测试"""

    @pytest.mark.timeout(120)
    def test_collect_via_data_type(self):
        from src.datacollect.collectors.yfinance_collector import YfinanceCollector
        from src.datacollect.base import CollectTask

        collector = YfinanceCollector()
        task = CollectTask(source="yfinance", data_type="vix", params={})
        try:
            result = collector.collect(task)
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"yfinance collect 网络不可达: {exc}")

        assert result.source == "yfinance"
        assert result.metadata["records_count"] >= 0

        time.sleep(YFINANCE_PAUSE)


class TestYfinanceHealthCheck:
    """yfinance 整体健康检查"""

    @pytest.mark.timeout(120)
    def test_health_check(self):
        try:
            import yfinance  # noqa: F401
        except ImportError:
            pytest.skip("yfinance 未安装")

        from src.datacollect.collectors.yfinance_collector import YfinanceCollector

        collector = YfinanceCollector()
        try:
            ok = collector.health_check()
        except _NETWORK_ERRORS:
            pytest.skip("yfinance 网络不可达")
        if not ok:
            pytest.skip("yfinance 健康检查返回空 (可能被限流)")


# ====================================================================
# 新浪财经全球 (sina_global) — Tier 2 备用源
# ====================================================================

class TestSinaGlobalIndex:
    """新浪全球指数采集"""

    @pytest.mark.timeout(120)
    def test_fetch_global_index(self):
        from src.datacollect.collectors.sina_global_collector import SinaGlobalCollector

        collector = SinaGlobalCollector()
        try:
            rows = collector.fetch_global_index()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"新浪全球指数网络不可达: {exc}")

        assert isinstance(rows, list)
        assert len(rows) > 0, "新浪全球指数返回空"
        symbols = [r["symbol"] for r in rows]
        assert any(s in symbols for s in ("DJI", "NASDAQ", "SPX")), (
            f"新浪缺少核心指数, 实际: {symbols}"
        )


class TestSinaForex:
    """新浪外汇"""

    @pytest.mark.timeout(120)
    def test_fetch_forex(self):
        from src.datacollect.collectors.sina_global_collector import SinaGlobalCollector

        collector = SinaGlobalCollector()
        try:
            rows = collector.fetch_forex()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"新浪外汇网络不可达: {exc}")

        assert isinstance(rows, list)
        if rows:
            usdcny = [r for r in rows if r["symbol"] == "USDCNY"]
            if usdcny:
                assert usdcny[0]["close_price"] is not None


class TestSinaCommodities:
    """新浪商品期货 (黄金 + 原油)"""

    @pytest.mark.timeout(120)
    def test_fetch_gold(self):
        from src.datacollect.collectors.sina_global_collector import SinaGlobalCollector

        collector = SinaGlobalCollector()
        try:
            rows = collector.fetch_gold()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"新浪黄金网络不可达: {exc}")

        assert isinstance(rows, list)

    @pytest.mark.timeout(120)
    def test_fetch_crude_oil(self):
        from src.datacollect.collectors.sina_global_collector import SinaGlobalCollector

        collector = SinaGlobalCollector()
        try:
            rows = collector.fetch_crude_oil()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"新浪原油网络不可达: {exc}")

        assert isinstance(rows, list)


class TestSinaFTSEA50:
    """新浪富时 A50"""

    @pytest.mark.timeout(120)
    def test_fetch_ftse_a50(self):
        from src.datacollect.collectors.sina_global_collector import SinaGlobalCollector

        collector = SinaGlobalCollector()
        try:
            rows = collector.fetch_ftse_a50()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"新浪富时 A50 网络不可达: {exc}")

        assert isinstance(rows, list)


class TestSinaHealthCheck:
    """新浪全球整体健康检查"""

    @pytest.mark.timeout(120)
    def test_health_check(self):
        from src.datacollect.collectors.sina_global_collector import SinaGlobalCollector

        collector = SinaGlobalCollector()
        try:
            ok = collector.health_check()
        except _NETWORK_ERRORS:
            pytest.skip("新浪全球网络不可达")
        assert ok is True, "新浪全球健康检查失败"
