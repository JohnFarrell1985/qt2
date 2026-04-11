"""Tests for src/data/download_progress.py — DownloadProgressDAO"""
from datetime import date, datetime
from unittest.mock import patch, MagicMock

import pytest

from src.data.models import StockDownloadProgress


def _make_record(**overrides) -> StockDownloadProgress:
    defaults = dict(
        id=1,
        code="000001.SZ",
        sync_type="history_full",
        status="pending",
        retry_count=0,
        max_retries=3,
        start_date=None,
        end_date=None,
        actual_start_date=None,
        actual_end_date=None,
        records_count=None,
        expected_count=None,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
        completed_at=None,
        error_message=None,
    )
    defaults.update(overrides)
    rec = StockDownloadProgress()
    for k, v in defaults.items():
        setattr(rec, k, v)
    return rec


@pytest.fixture
def mock_session():
    session = MagicMock()
    return session


@pytest.fixture
def dao():
    from src.data.download_progress import DownloadProgressDAO
    return DownloadProgressDAO()


class TestInitProgress:

    def test_empty_codes_returns_zero(self, dao):
        assert dao.init_progress([], "history_full") == 0

    @patch("src.data.download_progress.get_session")
    def test_all_new_codes(self, mock_get_session, dao):
        session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        query_mock = MagicMock()
        query_mock.filter.return_value.all.return_value = []
        session.query.return_value = query_mock

        result = dao.init_progress(
            ["000001.SZ", "000002.SZ"],
            "history_full",
            start_date=date(2020, 1, 1),
            end_date=date(2026, 1, 1),
        )

        assert result == 2
        session.bulk_save_objects.assert_called_once()
        objs = session.bulk_save_objects.call_args[0][0]
        assert len(objs) == 2
        assert all(o.status == "pending" for o in objs)
        assert all(o.max_retries == 3 for o in objs)

    @patch("src.data.download_progress.get_session")
    def test_mixed_existing_and_new(self, mock_get_session, dao):
        session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        existing_row = MagicMock()
        existing_row.code = "000001.SZ"
        query_mock = MagicMock()
        query_mock.filter.return_value.all.return_value = [existing_row]
        query_mock.filter.return_value.update = MagicMock(return_value=1)
        session.query.return_value = query_mock

        result = dao.init_progress(
            ["000001.SZ", "000002.SZ"], "history_full"
        )

        assert result == 2
        query_mock.filter.return_value.update.assert_called_once()
        session.bulk_save_objects.assert_called_once()
        new_objs = session.bulk_save_objects.call_args[0][0]
        assert len(new_objs) == 1
        assert new_objs[0].code == "000002.SZ"


class TestUpdateProgress:

    @patch("src.data.download_progress.get_session")
    def test_updates_existing_record(self, mock_get_session, dao):
        session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        query_mock = MagicMock()
        query_mock.filter.return_value.update.return_value = 1
        session.query.return_value = query_mock

        result = dao.update_progress("000001.SZ", "history_full", "running")

        assert result is True
        query_mock.filter.return_value.update.assert_called_once()

    @patch("src.data.download_progress.get_session")
    def test_returns_false_when_not_found(self, mock_get_session, dao):
        session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        query_mock = MagicMock()
        query_mock.filter.return_value.update.return_value = 0
        session.query.return_value = query_mock

        result = dao.update_progress("999999.SZ", "history_full", "running")

        assert result is False


class TestMarkFailed:

    @patch("src.data.download_progress.get_session")
    def test_increments_retry_and_stays_pending(self, mock_get_session, dao):
        session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        record = _make_record(retry_count=0, max_retries=3)
        query_mock = MagicMock()
        query_mock.filter.return_value.first.return_value = record
        session.query.return_value = query_mock

        dao.mark_failed("000001.SZ", "history_full", "connection timeout")

        assert record.retry_count == 1
        assert record.status == "pending"
        assert record.error_message == "connection timeout"

    @patch("src.data.download_progress.get_session")
    def test_marks_failed_when_retries_exhausted(self, mock_get_session, dao):
        session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        record = _make_record(retry_count=2, max_retries=3)
        query_mock = MagicMock()
        query_mock.filter.return_value.first.return_value = record
        session.query.return_value = query_mock

        dao.mark_failed("000001.SZ", "history_full", "still failing")

        assert record.retry_count == 3
        assert record.status == "failed"

    @patch("src.data.download_progress.get_session")
    def test_truncates_long_error_message(self, mock_get_session, dao):
        session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        record = _make_record(retry_count=0, max_retries=3)
        query_mock = MagicMock()
        query_mock.filter.return_value.first.return_value = record
        session.query.return_value = query_mock

        long_msg = "x" * 1000
        dao.mark_failed("000001.SZ", "history_full", long_msg)

        assert len(record.error_message) == 500

    @patch("src.data.download_progress.get_session")
    def test_noop_when_record_not_found(self, mock_get_session, dao):
        session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        query_mock = MagicMock()
        query_mock.filter.return_value.first.return_value = None
        session.query.return_value = query_mock

        dao.mark_failed("999999.SZ", "history_full", "error")


class TestMarkCompleted:

    @patch("src.data.download_progress.get_session")
    def test_sets_success_and_completed_at(self, mock_get_session, dao):
        session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        query_mock = MagicMock()
        query_mock.filter.return_value.update.return_value = 1
        session.query.return_value = query_mock

        dao.mark_completed("000001.SZ", "history_full", records_count=250)

        update_args = query_mock.filter.return_value.update.call_args[0][0]
        assert update_args[StockDownloadProgress.status] == "success"
        assert update_args[StockDownloadProgress.records_count] == 250
        assert StockDownloadProgress.completed_at in update_args


class TestGetIncompleteStocks:

    @patch("src.data.download_progress.get_session")
    def test_returns_code_list(self, mock_get_session, dao):
        session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        row1 = MagicMock()
        row1.code = "000001.SZ"
        row2 = MagicMock()
        row2.code = "000002.SZ"
        query_mock = MagicMock()
        query_mock.filter.return_value.all.return_value = [row1, row2]
        session.query.return_value = query_mock

        result = dao.get_incomplete_stocks("history_full")

        assert result == ["000001.SZ", "000002.SZ"]

    @patch("src.data.download_progress.get_session")
    def test_returns_empty_when_all_complete(self, mock_get_session, dao):
        session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        query_mock = MagicMock()
        query_mock.filter.return_value.all.return_value = []
        session.query.return_value = query_mock

        result = dao.get_incomplete_stocks("history_full")

        assert result == []


class TestGetDownloadSummary:

    @patch("src.data.download_progress.get_session")
    def test_aggregates_by_status(self, mock_get_session, dao):
        session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        query_mock = MagicMock()
        query_mock.filter.return_value.group_by.return_value.all.return_value = [
            ("pending", 10),
            ("running", 2),
            ("success", 50),
            ("failed", 3),
        ]
        session.query.return_value = query_mock

        result = dao.get_download_summary("history_full")

        assert result == {
            "pending": 10,
            "running": 2,
            "success": 50,
            "failed": 3,
            "total": 65,
        }

    @patch("src.data.download_progress.get_session")
    def test_empty_table_returns_zeros(self, mock_get_session, dao):
        session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        query_mock = MagicMock()
        query_mock.filter.return_value.group_by.return_value.all.return_value = []
        session.query.return_value = query_mock

        result = dao.get_download_summary("history_full")

        assert result == {
            "pending": 0, "running": 0, "success": 0, "failed": 0, "total": 0,
        }


class TestResetFailed:

    @patch("src.data.download_progress.get_session")
    def test_resets_and_returns_count(self, mock_get_session, dao):
        session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        query_mock = MagicMock()
        query_mock.filter.return_value.update.return_value = 5
        session.query.return_value = query_mock

        result = dao.reset_failed("history_full")

        assert result == 5
        update_args = query_mock.filter.return_value.update.call_args[0][0]
        assert update_args[StockDownloadProgress.status] == "pending"
        assert update_args[StockDownloadProgress.retry_count] == 0
