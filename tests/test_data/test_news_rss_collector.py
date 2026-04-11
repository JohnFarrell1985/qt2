"""Tests for NewsRssCollector"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.datacollect.base import CollectTask
from src.datacollect.collectors.news_rss_collector import NewsRssCollector


@pytest.fixture
def mock_limiter():
    limiter = MagicMock()
    limiter.acquire.return_value = True
    return limiter


@pytest.fixture
def collector(mock_limiter):
    feeds = [{"name": "test_feed", "url": "http://test.com/rss", "label": "Test Feed"}]
    return NewsRssCollector(limiter=mock_limiter, feeds=feeds)


def _mock_feed_result(entries):
    parsed = MagicMock()
    parsed.entries = entries
    return parsed


class TestParseFeed:
    def test_parse_entries(self, collector):
        entry1 = MagicMock()
        entry1.title = "测试新闻标题"
        entry1.summary = "新闻摘要内容"
        entry1.link = "http://example.com/1"
        entry1.published_parsed = (2026, 4, 2, 10, 0, 0, 0, 0, 0)

        mock_fp = MagicMock()
        mock_fp.parse.return_value = _mock_feed_result([entry1])
        with patch.dict("sys.modules", {"feedparser": mock_fp}):
            items = collector._parse_feed("http://test.com", "test", "Test")
        assert len(items) == 1
        assert items[0]["title"] == "测试新闻标题"
        assert items[0]["source"] == "Test"
        assert isinstance(items[0]["published_at"], datetime)

    def test_import_error(self, collector):
        with patch.dict("sys.modules", {"feedparser": None}):
            with patch("builtins.__import__", side_effect=ImportError("no feedparser")):
                with pytest.raises(RuntimeError, match="feedparser 未安装"):
                    collector._parse_feed("http://test.com", "test", "Test")


class TestFetchAllNews:
    def test_aggregates_feeds(self, collector):
        items = [{"title": "news1"}, {"title": "news2"}]
        with patch.object(collector, "_parse_feed", return_value=items):
            result = collector.fetch_all_news()
        assert len(result) == 2

    def test_handles_feed_failure(self, collector):
        with patch.object(collector, "_parse_feed", side_effect=RuntimeError("fail")):
            result = collector.fetch_all_news()
        assert result == []


class TestCollect:
    def test_collect_returns_result(self, collector):
        with patch.object(collector, "fetch_all_news", return_value=[{"title": "news"}]):
            task = CollectTask(data_type="financial_news", params={})
            result = collector.collect(task)
        assert result.source == "rss_aggregator"
        assert result.metadata["records_count"] == 1


class TestHealthCheck:
    def test_healthy(self, collector):
        with patch.object(collector, "_parse_feed", return_value=[{"title": "ok"}]):
            assert collector.health_check() is True

    def test_empty(self, collector):
        with patch.object(collector, "_parse_feed", return_value=[]):
            assert collector.health_check() is False

    def test_no_feeds(self, mock_limiter):
        c = NewsRssCollector(limiter=mock_limiter, feeds=[])
        assert c.health_check() is False
