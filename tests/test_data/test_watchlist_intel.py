"""Tests for WatchlistSync (A22) and WatchlistIntelCollector (A23)"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.datacollect.watchlist_intel import WatchlistIntelCollector, WatchlistSync
from src.datacollect.base import CollectTask


# ====================================================================
# Helpers: mock DB session context manager
# ====================================================================

def _make_mock_session():
    """Create a mock session that works as a context manager and tracks calls."""
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


def _make_watchlist_stock(code: str, name: str = "", source: str = "qmt", is_active: bool = True):
    """Create a mock WatchlistStock row."""
    stock = MagicMock()
    stock.code = code
    stock.name = name
    stock.source = source
    stock.is_active = is_active
    stock.added_at = datetime(2025, 1, 1)
    stock.removed_at = None
    return stock


# ====================================================================
# WatchlistSync
# ====================================================================

class TestSyncCodes:
    """Test _sync_codes — the internal diff engine."""

    @patch("src.datacollect.watchlist_intel.get_session")
    def test_sync_codes_add_new(self, mock_get_session):
        session = _make_mock_session()
        mock_get_session.return_value = session
        session.query.return_value.filter.return_value.all.return_value = []

        sync = WatchlistSync()
        result = sync._sync_codes(["000001.SZ", "000002.SZ"], source="csv")

        assert result["added"] == 2
        assert result["removed"] == 0
        assert result["unchanged"] == 0
        assert session.add.call_count == 2

    @patch("src.datacollect.watchlist_intel.get_session")
    def test_sync_codes_remove(self, mock_get_session):
        session = _make_mock_session()
        mock_get_session.return_value = session

        existing = [
            _make_watchlist_stock("000001.SZ"),
            _make_watchlist_stock("000003.SZ"),
        ]
        session.query.return_value.filter.return_value.all.return_value = existing

        sync = WatchlistSync()
        result = sync._sync_codes(["000001.SZ"], source="qmt")

        assert result["added"] == 0
        assert result["removed"] == 1
        assert result["unchanged"] == 1
        assert existing[1].is_active is False

    @patch("src.datacollect.watchlist_intel.get_session")
    def test_sync_codes_mixed(self, mock_get_session):
        session = _make_mock_session()
        mock_get_session.return_value = session

        existing = [_make_watchlist_stock("000001.SZ")]
        session.query.return_value.filter.return_value.all.return_value = existing

        sync = WatchlistSync()
        result = sync._sync_codes(
            ["000001.SZ", "000002.SZ"],
            source="csv",
            names={"000002.SZ": "万科A"},
        )

        assert result["added"] == 1
        assert result["removed"] == 0
        assert result["unchanged"] == 1


class TestSyncFromCsv:
    @patch("src.datacollect.watchlist_intel.get_session")
    def test_sync_from_csv(self, mock_get_session, tmp_path):
        session = _make_mock_session()
        mock_get_session.return_value = session
        session.query.return_value.filter.return_value.all.return_value = []

        csv_file = tmp_path / "watchlist.csv"
        csv_file.write_text("code,name\n000001.SZ,平安银行\n000002.SZ,万科A\n", encoding="utf-8")

        sync = WatchlistSync()
        result = sync.sync_from_csv(csv_file)

        assert result["added"] == 2
        assert "error" not in result

    def test_sync_from_csv_file_not_found(self):
        sync = WatchlistSync()
        result = sync.sync_from_csv("/nonexistent/path.csv")

        assert result["error"] == "file_not_found"
        assert result["added"] == 0


class TestSyncFromJson:
    @patch("src.datacollect.watchlist_intel.get_session")
    def test_sync_from_json(self, mock_get_session, tmp_path):
        session = _make_mock_session()
        mock_get_session.return_value = session
        session.query.return_value.filter.return_value.all.return_value = []

        json_file = tmp_path / "watchlist.json"
        json_file.write_text(
            '[{"code": "000001.SZ", "name": "平安银行"}]', encoding="utf-8"
        )

        sync = WatchlistSync()
        result = sync.sync_from_json(json_file)

        assert result["added"] == 1

    def test_sync_from_json_file_not_found(self):
        sync = WatchlistSync()
        result = sync.sync_from_json("/nonexistent/path.json")

        assert result["error"] == "file_not_found"


class TestAddManual:
    @patch("src.datacollect.watchlist_intel.get_session")
    def test_add_manual_new(self, mock_get_session):
        session = _make_mock_session()
        mock_get_session.return_value = session
        session.query.return_value.filter.return_value.first.return_value = None

        sync = WatchlistSync()
        assert sync.add_manual("000001.SZ", "平安银行") is True
        session.add.assert_called_once()

    @patch("src.datacollect.watchlist_intel.get_session")
    def test_add_manual_duplicate(self, mock_get_session):
        session = _make_mock_session()
        mock_get_session.return_value = session
        session.query.return_value.filter.return_value.first.return_value = (
            _make_watchlist_stock("000001.SZ")
        )

        sync = WatchlistSync()
        assert sync.add_manual("000001.SZ") is False
        session.add.assert_not_called()


class TestRemove:
    @patch("src.datacollect.watchlist_intel.get_session")
    def test_remove_existing(self, mock_get_session):
        session = _make_mock_session()
        mock_get_session.return_value = session
        stock = _make_watchlist_stock("000001.SZ")
        session.query.return_value.filter.return_value.first.return_value = stock

        sync = WatchlistSync()
        assert sync.remove("000001.SZ") is True
        assert stock.is_active is False

    @patch("src.datacollect.watchlist_intel.get_session")
    def test_remove_not_found(self, mock_get_session):
        session = _make_mock_session()
        mock_get_session.return_value = session
        session.query.return_value.filter.return_value.first.return_value = None

        sync = WatchlistSync()
        assert sync.remove("999999.SZ") is False


class TestGetActive:
    @patch("src.datacollect.watchlist_intel.get_session")
    def test_get_active(self, mock_get_session):
        session = _make_mock_session()
        mock_get_session.return_value = session
        stocks = [
            _make_watchlist_stock("000001.SZ", "平安银行"),
            _make_watchlist_stock("000002.SZ", "万科A"),
        ]
        session.query.return_value.filter.return_value.order_by.return_value.all.return_value = (
            stocks
        )

        sync = WatchlistSync()
        result = sync.get_active()

        assert len(result) == 2
        assert result[0]["code"] == "000001.SZ"
        assert result[1]["name"] == "万科A"


class TestSyncFromQmt:
    @patch("src.datacollect.watchlist_intel.get_session")
    def test_sync_from_qmt_no_sdk(self, mock_get_session):
        """xtquant unavailable → graceful fallback."""
        sync = WatchlistSync()
        result = sync.sync_from_qmt()

        assert result["error"] == "xtquant_unavailable"
        assert result["added"] == 0


# ====================================================================
# WatchlistIntelCollector
# ====================================================================

class TestWatchlistIntelCollect:
    def test_collect_missing_code(self):
        collector = WatchlistIntelCollector()
        task = CollectTask(source="akshare", data_type="watchlist_news", params={})
        with pytest.raises(ValueError, match="must contain 'code'"):
            collector.collect(task)

    def test_collect_unknown_type(self):
        collector = WatchlistIntelCollector()
        task = CollectTask(
            source="akshare",
            data_type="watchlist_unknown",
            params={"code": "000001.SZ", "intel_type": "unknown"},
        )
        with pytest.raises(ValueError, match="Unknown intel_type"):
            collector.collect(task)

    @patch("src.datacollect.watchlist_intel.WatchlistIntelCollector._collect_news")
    def test_collect_news_dispatch(self, mock_news):
        mock_news.return_value = [{"title": "test"}]
        collector = WatchlistIntelCollector()
        task = CollectTask(
            source="akshare",
            data_type="watchlist_news",
            params={"code": "000001.SZ", "intel_type": "news"},
        )
        result = collector.collect(task)

        mock_news.assert_called_once_with("000001.SZ")
        assert result.metadata["count"] == 1

    @patch("src.datacollect.watchlist_intel.WatchlistIntelCollector._collect_announcements")
    def test_collect_announcement_dispatch(self, mock_ann):
        mock_ann.return_value = [{"title": "公告1"}, {"title": "公告2"}]
        collector = WatchlistIntelCollector()
        task = CollectTask(
            source="akshare",
            data_type="watchlist_announcement",
            params={"code": "000001.SZ", "intel_type": "announcement"},
        )
        result = collector.collect(task)

        mock_ann.assert_called_once_with("000001.SZ")
        assert result.metadata["count"] == 2

    @patch("src.datacollect.watchlist_intel.WatchlistIntelCollector._collect_capital_flow")
    def test_collect_capital_flow_dispatch(self, mock_cf):
        mock_cf.return_value = []
        collector = WatchlistIntelCollector()
        task = CollectTask(
            source="akshare",
            data_type="watchlist_capital_flow",
            params={"code": "000001.SZ", "intel_type": "capital_flow"},
        )
        result = collector.collect(task)

        mock_cf.assert_called_once_with("000001.SZ")
        assert result.metadata["count"] == 0


class TestCollectWithLimiter:
    @patch("src.datacollect.watchlist_intel.WatchlistIntelCollector._collect_news")
    def test_limiter_acquire_called(self, mock_news):
        mock_news.return_value = []
        limiter = MagicMock()
        collector = WatchlistIntelCollector(limiter=limiter)
        task = CollectTask(
            source="akshare",
            data_type="watchlist_news",
            params={"code": "000001.SZ", "intel_type": "news"},
        )
        collector.collect(task)

        limiter.acquire.assert_called_once()


class TestHealthCheck:
    @patch.dict("sys.modules", {"akshare": MagicMock()})
    def test_health_check_ok(self):
        collector = WatchlistIntelCollector()
        assert collector.health_check() is True

    def test_health_check_missing(self):
        import sys
        saved = sys.modules.get("akshare")
        sys.modules["akshare"] = None  # force ImportError
        try:
            collector = WatchlistIntelCollector()
            assert collector.health_check() is False
        finally:
            if saved is None:
                sys.modules.pop("akshare", None)
            else:
                sys.modules["akshare"] = saved


class TestCollectAndSave:
    @patch("src.datacollect.watchlist_intel.WatchlistIntelCollector._save_intel")
    @patch("src.datacollect.watchlist_intel.WatchlistIntelCollector.collect")
    def test_collect_and_save(self, mock_collect, mock_save):
        mock_collect.return_value = CollectTask  # will use .data
        mock_collect.return_value = MagicMock(data=[{"title": "t1"}, {"title": "t2"}])
        mock_save.return_value = 2

        collector = WatchlistIntelCollector()
        stats = collector.collect_and_save("000001.SZ", intel_types=["news"])

        assert stats["news"] == 2
        mock_save.assert_called_once()

    @patch("src.datacollect.watchlist_intel.WatchlistIntelCollector.collect")
    def test_collect_and_save_handles_error(self, mock_collect):
        mock_collect.side_effect = RuntimeError("api error")
        collector = WatchlistIntelCollector()
        stats = collector.collect_and_save("000001.SZ", intel_types=["news"])

        assert stats["news"] == 0


class TestCollectAllWatchlist:
    @patch("src.datacollect.watchlist_intel.WatchlistIntelCollector.collect_and_save")
    @patch("src.datacollect.watchlist_intel.WatchlistSync.get_active")
    def test_collect_all_watchlist(self, mock_active, mock_cas):
        mock_active.return_value = [
            {"code": "000001.SZ", "name": "平安", "source": "qmt", "added_at": None},
            {"code": "000002.SZ", "name": "万科", "source": "qmt", "added_at": None},
        ]
        mock_cas.return_value = {"news": 5, "announcement": 2}

        collector = WatchlistIntelCollector()
        result = collector.collect_all_watchlist(intel_types=["news", "announcement"])

        assert result["stocks"] == 2
        assert mock_cas.call_count == 2
        assert result["stats"]["news"] == 10
        assert result["stats"]["announcement"] == 4


class TestSaveIntel:
    @patch("src.datacollect.watchlist_intel.get_session")
    def test_save_intel(self, mock_get_session):
        session = _make_mock_session()
        mock_get_session.return_value = session

        collector = WatchlistIntelCollector()
        records = [
            {"title": "新闻1", "content": "内容1", "source": "eastmoney", "url": "http://...", "published_at": "2025-01-01"},
            {"title": "新闻2", "content": "内容2", "source": "eastmoney", "url": "", "published_at": ""},
        ]
        saved = collector._save_intel("000001.SZ", "news", records)

        assert saved == 2
        assert session.add.call_count == 2


class TestParseDatetime:
    def test_none(self):
        assert WatchlistIntelCollector._parse_datetime(None) is None

    def test_empty_string(self):
        assert WatchlistIntelCollector._parse_datetime("") is None

    def test_datetime_passthrough(self):
        dt = datetime(2025, 1, 1)
        assert WatchlistIntelCollector._parse_datetime(dt) is dt

    def test_string_parse(self):
        result = WatchlistIntelCollector._parse_datetime("2025-01-01 12:00:00")
        assert result is not None
        assert result.year == 2025

    def test_invalid_string(self):
        assert WatchlistIntelCollector._parse_datetime("not-a-date") is None
