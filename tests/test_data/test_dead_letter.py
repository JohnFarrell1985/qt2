"""Tests for src/datacollect/dead_letter.py + CollectDeadLetter model"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from src.datacollect.dead_letter import DeadLetterDAO
from src.datacollect.models import CollectDeadLetter


def _make_dead_letter(**overrides) -> MagicMock:
    defaults = dict(
        id=1,
        task_id="abc123",
        source="akshare",
        data_type="stock_daily",
        error_type="timeout",
        error_msg="connection timed out",
        payload={"func": "stock_zh_a_hist"},
        retry_count=0,
        max_retries=3,
        next_retry_at=None,
        created_at=datetime(2024, 1, 1),
        resolved_at=None,
    )
    defaults.update(overrides)
    dl = MagicMock(spec=CollectDeadLetter)
    for k, v in defaults.items():
        setattr(dl, k, v)
    return dl


class TestDeadLetterDAO:

    @pytest.fixture
    def dao(self) -> DeadLetterDAO:
        return DeadLetterDAO(backoff_base=60.0)

    @pytest.fixture
    def session(self) -> MagicMock:
        return MagicMock()

    # ------------------------------------------------------------------
    # enqueue
    # ------------------------------------------------------------------

    def test_enqueue_creates_record(self, dao: DeadLetterDAO, session: MagicMock):
        result = dao.enqueue(
            session, task_id="t1", source="akshare", data_type="stock_daily",
            error_type="timeout", error_msg="conn timeout", payload={"x": 1},
        )
        session.add.assert_called_once()
        session.flush.assert_called_once()
        assert isinstance(result, CollectDeadLetter)
        assert result.task_id == "t1"
        assert result.source == "akshare"
        assert result.retry_count == 0
        assert result.max_retries == 3

    def test_enqueue_custom_max_retries(self, dao: DeadLetterDAO, session: MagicMock):
        result = dao.enqueue(
            session, task_id="t2", source="tushare", data_type="stock_list",
            error_type="rate_limit", error_msg="429", max_retries=5,
        )
        assert result.max_retries == 5

    # ------------------------------------------------------------------
    # get_pending
    # ------------------------------------------------------------------

    def test_get_pending_returns_list(self, dao: DeadLetterDAO, session: MagicMock):
        mock_query = session.query.return_value
        mock_filter = mock_query.filter.return_value
        mock_order = mock_filter.order_by.return_value
        mock_limit = mock_order.limit.return_value
        mock_limit.all.return_value = [_make_dead_letter()]

        result = dao.get_pending(session, limit=10)
        assert len(result) == 1
        session.query.assert_called_once_with(CollectDeadLetter)

    # ------------------------------------------------------------------
    # mark_resolved
    # ------------------------------------------------------------------

    def test_mark_resolved_sets_timestamp(self, dao: DeadLetterDAO, session: MagicMock):
        dl = _make_dead_letter(id=5)
        session.get.return_value = dl

        dao.mark_resolved(session, dead_letter_id=5)
        assert dl.resolved_at is not None
        session.flush.assert_called_once()

    def test_mark_resolved_not_found(self, dao: DeadLetterDAO, session: MagicMock):
        session.get.return_value = None
        dao.mark_resolved(session, dead_letter_id=999)
        session.flush.assert_not_called()

    # ------------------------------------------------------------------
    # increment_retry
    # ------------------------------------------------------------------

    def test_increment_retry_exponential_backoff(self, dao: DeadLetterDAO, session: MagicMock):
        dl = _make_dead_letter(id=3, retry_count=1)
        session.get.return_value = dl

        before = datetime.now()
        dao.increment_retry(session, dead_letter_id=3)
        assert dl.retry_count == 2
        assert dl.next_retry_at is not None
        expected_backoff = 60.0 * (2 ** 2)
        assert dl.next_retry_at >= before + timedelta(seconds=expected_backoff - 1)

    def test_increment_retry_custom_seconds(self, dao: DeadLetterDAO, session: MagicMock):
        dl = _make_dead_letter(id=4, retry_count=0)
        session.get.return_value = dl

        before = datetime.now()
        dao.increment_retry(session, dead_letter_id=4, next_retry_seconds=30)
        assert dl.retry_count == 1
        assert dl.next_retry_at >= before + timedelta(seconds=29)
        assert dl.next_retry_at <= before + timedelta(seconds=32)

    def test_increment_retry_not_found(self, dao: DeadLetterDAO, session: MagicMock):
        session.get.return_value = None
        dao.increment_retry(session, dead_letter_id=999)
        session.flush.assert_not_called()

    # ------------------------------------------------------------------
    # get_stats
    # ------------------------------------------------------------------

    def test_get_stats(self, dao: DeadLetterDAO, session: MagicMock):
        total_q = MagicMock()
        total_q.scalar.return_value = 10

        resolved_q = MagicMock()
        resolved_q.scalar.return_value = 4

        exhausted_q = MagicMock()
        exhausted_q.scalar.return_value = 2

        def _scalar():
            return 10

        query_mock = MagicMock()
        query_mock.scalar.return_value = 10
        filter_tracker = [0]

        def _filter(*args, **kwargs):
            m = MagicMock()
            idx = filter_tracker[0]
            if idx == 0:
                m.scalar.return_value = 4
            else:
                m.scalar.return_value = 2
                m.filter.return_value = m
            filter_tracker[0] += 1
            m.filter.return_value = m
            return m

        query_mock.filter.side_effect = _filter
        session.query.return_value = query_mock

        result = dao.get_stats(session)
        assert isinstance(result, dict)
        assert "total" in result
        assert "pending" in result
        assert "resolved" in result
        assert "exhausted" in result
