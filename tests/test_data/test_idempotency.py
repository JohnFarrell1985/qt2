"""Tests for src/datacollect/idempotency.py + CollectTask 幂等键"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.datacollect.base import CollectTask
from src.datacollect.idempotency import IdempotencyChecker
from src.datacollect.models import CollectLog


# ====================================================================
# CollectTask idempotency_key
# ====================================================================

class TestCollectTaskIdempotencyKey:

    def test_auto_generated(self):
        task = CollectTask(source="akshare", data_type="stock_daily", params={"func": "hist"})
        assert task.idempotency_key
        assert len(task.idempotency_key) == 16

    def test_deterministic(self):
        t1 = CollectTask(source="akshare", data_type="stock_daily", params={"a": 1, "b": 2})
        t2 = CollectTask(source="akshare", data_type="stock_daily", params={"b": 2, "a": 1})
        assert t1.idempotency_key == t2.idempotency_key

    def test_different_source_different_key(self):
        t1 = CollectTask(source="akshare", data_type="stock_daily", params={"func": "hist"})
        t2 = CollectTask(source="tushare", data_type="stock_daily", params={"func": "hist"})
        assert t1.idempotency_key != t2.idempotency_key

    def test_different_data_type_different_key(self):
        t1 = CollectTask(source="akshare", data_type="stock_daily", params={})
        t2 = CollectTask(source="akshare", data_type="stock_list", params={})
        assert t1.idempotency_key != t2.idempotency_key

    def test_different_params_different_key(self):
        t1 = CollectTask(source="akshare", data_type="stock_daily", params={"code": "000001"})
        t2 = CollectTask(source="akshare", data_type="stock_daily", params={"code": "600000"})
        assert t1.idempotency_key != t2.idempotency_key

    def test_explicit_key_preserved(self):
        task = CollectTask(
            source="akshare", data_type="stock_daily",
            params={}, idempotency_key="custom_key_12345",
        )
        assert task.idempotency_key == "custom_key_12345"

    def test_data_type_field_exists(self):
        task = CollectTask(source="x", data_type="y")
        assert task.data_type == "y"

    def test_backward_compat_default(self):
        task = CollectTask(source="x")
        assert task.data_type == ""
        assert task.idempotency_key


# ====================================================================
# IdempotencyChecker
# ====================================================================

class TestIdempotencyChecker:

    @pytest.fixture
    def session(self) -> MagicMock:
        return MagicMock()

    def test_is_duplicate_true(self, session: MagicMock):
        mock_result = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = mock_result

        assert IdempotencyChecker.is_duplicate(session, "abc123") is True

    def test_is_duplicate_false(self, session: MagicMock):
        session.query.return_value.filter.return_value.first.return_value = None

        assert IdempotencyChecker.is_duplicate(session, "abc123") is False

    def test_is_duplicate_respects_ttl(self, session: MagicMock):
        session.query.return_value.filter.return_value.first.return_value = None
        assert IdempotencyChecker.is_duplicate(session, "abc123", ttl_hours=1) is False
        session.query.assert_called()

    def test_record_success_updates_log(self, session: MagicMock):
        log = MagicMock(spec=CollectLog)
        session.query.return_value.filter.return_value.first.return_value = log

        IdempotencyChecker.record_success(session, "key123", "task456")
        assert log.idempotency_key == "key123"
        session.flush.assert_called_once()

    def test_record_success_missing_log(self, session: MagicMock):
        session.query.return_value.filter.return_value.first.return_value = None
        IdempotencyChecker.record_success(session, "key123", "missing_task")
        session.flush.assert_not_called()
