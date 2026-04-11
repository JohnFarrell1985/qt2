"""E2E: Tier 2 财经新闻 RSS 采集

原则: 2 分钟内无数据返回 = 数据源不可用, 彻底放弃。

测试各个 RSS feed 源的可达性和返回格式。
公共 RSSHub 实例 (rsshub.app) 目前返回 403, 需自建实例才可用;
36kr 原生 RSS 可直接使用。每个 feed 独立测试。
"""
import pytest

from src.datacollect.rate_limiter import TokenBucketLimiter

_NETWORK_ERRORS = (ConnectionError, OSError, RuntimeError, ImportError)


@pytest.fixture(autouse=True)
def _reset_limiters():
    yield
    TokenBucketLimiter.reset_all()


class TestNewsRss36kr:
    """36氪 RSS (原生, 无需 RSSHub)"""

    @pytest.mark.timeout(120)
    def test_36kr_feed(self):
        from src.datacollect.collectors.news_rss_collector import NewsRssCollector

        feeds = [{"name": "36kr", "url": "https://36kr.com/feed", "label": "36氪科技财经"}]
        collector = NewsRssCollector(feeds=feeds)
        try:
            items = collector.fetch_all_news()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"36kr RSS 不可达: {exc}")

        assert isinstance(items, list)
        assert len(items) > 0, "36kr RSS 返回空"
        assert items[0]["title"], "新闻标题为空"
        assert items[0]["source"] == "36氪科技财经"

    @pytest.mark.timeout(120)
    def test_36kr_article_feed(self):
        from src.datacollect.collectors.news_rss_collector import NewsRssCollector

        feeds = [{"name": "36kr_article", "url": "https://36kr.com/feed-article", "label": "36氪深度"}]
        collector = NewsRssCollector(feeds=feeds)
        try:
            items = collector.fetch_all_news()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"36kr 深度 RSS 不可达: {exc}")

        assert isinstance(items, list)
        assert len(items) > 0, "36kr 深度 RSS 返回空"


class TestNewsRssRssHub:
    """RSSHub 源可达性 — 公共实例 rsshub.app 通常 403, 需自建"""

    @pytest.mark.timeout(120)
    def test_cls_telegraph(self):
        from src.datacollect.collectors.news_rss_collector import NewsRssCollector

        feeds = [{"name": "cls_telegraph", "url": "https://rsshub.app/cls/telegraph", "label": "财联社快讯"}]
        collector = NewsRssCollector(feeds=feeds)
        try:
            items = collector.fetch_all_news()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"财联社 RSS 不可达: {exc}")

        if not items:
            pytest.skip("RSSHub cls/telegraph 返回空 (公共实例可能被封)")
        assert items[0]["title"]

    @pytest.mark.timeout(120)
    def test_wallstreetcn(self):
        from src.datacollect.collectors.news_rss_collector import NewsRssCollector

        feeds = [{"name": "wallstreetcn", "url": "https://rsshub.app/wallstreetcn/news/global", "label": "华尔街见闻"}]
        collector = NewsRssCollector(feeds=feeds)
        try:
            items = collector.fetch_all_news()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"华尔街见闻 RSS 不可达: {exc}")

        if not items:
            pytest.skip("RSSHub wallstreetcn 返回空 (公共实例可能被封)")


class TestNewsRssAllFeeds:
    """全部默认 RSS 源聚合测试"""

    @pytest.mark.timeout(120)
    def test_fetch_all_news(self):
        from src.datacollect.collectors.news_rss_collector import NewsRssCollector

        collector = NewsRssCollector()
        try:
            items = collector.fetch_all_news()
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"RSS 聚合不可达: {exc}")

        assert isinstance(items, list)
        assert len(items) > 0, "所有 RSS 源均无数据 (需检查网络或 RSSHub 实例)"

        for item in items[:5]:
            assert "title" in item
            assert "link" in item
            assert "source" in item


class TestNewsRssHealthCheck:
    """RSS 聚合器健康检查"""

    @pytest.mark.timeout(120)
    def test_health_check(self):
        try:
            import feedparser  # noqa: F401
        except ImportError:
            pytest.skip("feedparser 未安装")

        from src.datacollect.collectors.news_rss_collector import NewsRssCollector

        collector = NewsRssCollector()
        try:
            ok = collector.health_check()
        except _NETWORK_ERRORS:
            pytest.skip("RSS 网络不可达")
        assert ok is True, "RSS 聚合器健康检查失败 (首个源无法获取新闻)"
