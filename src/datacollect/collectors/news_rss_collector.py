"""财经新闻 RSS 聚合采集器 — Tier 2 情报信号

从多个财经 RSS 源采集新闻标题和摘要,
用于 SentimentDaily.news_sentiment_score 计算。
feedparser 仅在方法内延迟导入。
"""
from __future__ import annotations

import time
from datetime import datetime

from src.common.logger import get_logger
from src.datacollect.base import BaseCollector, CollectResult, CollectTask
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)

DEFAULT_FEEDS: list[dict[str, str]] = [
    {"name": "36kr", "url": "https://36kr.com/feed", "label": "36氪科技财经"},
    {"name": "36kr_article", "url": "https://36kr.com/feed-article", "label": "36氪深度"},
    {"name": "cls_telegraph", "url": "https://rsshub.app/cls/telegraph", "label": "财联社快讯"},
    {"name": "wallstreetcn", "url": "https://rsshub.app/wallstreetcn/news/global", "label": "华尔街见闻"},
    {"name": "eastmoney_news", "url": "https://rsshub.app/eastmoney/report", "label": "东方财富资讯"},
    {"name": "caixin", "url": "https://rsshub.app/caixin/latest", "label": "财新网"},
]


class NewsRssCollector(BaseCollector):
    """财经新闻 RSS 聚合采集器。

    Tier 2 情报采集, 通过 RSSHub 代理获取中文财经新闻 feed。
    """

    SOURCE = "rss_aggregator"

    def __init__(
        self,
        limiter: TokenBucketLimiter | None = None,
        feeds: list[dict[str, str]] | None = None,
    ):
        if limiter is None:
            limiter = TokenBucketLimiter.for_domain("rss", rate=1.0, burst=5)
        super().__init__(limiter)
        self._feeds = feeds if feeds is not None else DEFAULT_FEEDS

    def _parse_feed(self, feed_url: str, feed_name: str, feed_label: str) -> list[dict]:
        """Parse a single RSS feed and return normalized news items."""
        try:
            import feedparser
        except ImportError:
            raise RuntimeError("feedparser 未安装, 无法采集 RSS 新闻")

        if self._limiter:
            self._limiter.acquire()

        t0 = time.monotonic()
        parsed = feedparser.parse(feed_url)
        elapsed = (time.monotonic() - t0) * 1000
        logger.debug("RSS parse %s (%.0fms, %d entries)", feed_name, elapsed, len(parsed.entries))

        items: list[dict] = []
        for entry in parsed.entries[:50]:
            published = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                try:
                    published = datetime(*entry.published_parsed[:6])
                except Exception:
                    pass

            items.append({
                "title": getattr(entry, "title", ""),
                "summary": getattr(entry, "summary", "")[:500],
                "link": getattr(entry, "link", ""),
                "source": feed_label,
                "source_key": feed_name,
                "published_at": published,
            })
        return items

    def fetch_all_news(self) -> list[dict]:
        """Fetch news from all configured RSS feeds."""
        all_items: list[dict] = []
        for feed in self._feeds:
            try:
                items = self._parse_feed(feed["url"], feed["name"], feed["label"])
                all_items.extend(items)
            except Exception as e:
                logger.warning("RSS feed %s 采集失败: %s", feed["name"], e)
        logger.info("RSS 采集完成: %d 条新闻 from %d feeds", len(all_items), len(self._feeds))
        return all_items

    def collect(self, task: CollectTask) -> CollectResult:
        t0 = time.monotonic()
        data = self.fetch_all_news()
        elapsed_ms = (time.monotonic() - t0) * 1000

        return CollectResult(
            source=self.SOURCE,
            data=data,
            collected_at=datetime.now(),
            metadata={
                "task_id": task.task_id,
                "func_name": "fetch_all_news",
                "records_count": len(data),
                "elapsed_ms": round(elapsed_ms, 1),
            },
        )

    def health_check(self) -> bool:
        try:
            if not self._feeds:
                return False
            items = self._parse_feed(
                self._feeds[0]["url"],
                self._feeds[0]["name"],
                self._feeds[0]["label"],
            )
            ok = len(items) > 0
            logger.info("rss_aggregator 健康检查: %s (%d items)", "OK" if ok else "EMPTY", len(items))
            return ok
        except Exception as e:
            logger.warning("rss_aggregator 健康检查失败: %s", e)
            return False
