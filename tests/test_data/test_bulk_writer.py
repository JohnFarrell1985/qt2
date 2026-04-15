"""Tests for src/data/bulk_writer.py"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from src.data.bulk_writer import BulkWriter


# ====================================================================
# Helpers
# ====================================================================


class FakeModel:
    __tablename__ = "fake_table"


class FakeModelWithPK:
    __tablename__ = "fake_pk_table"


# ====================================================================
# write — empty records
# ====================================================================


class TestWriteEmpty:

    def test_empty_records_returns_zero(self):
        writer = BulkWriter()
        result = writer.write(FakeModel, [])
        assert result == 0


# ====================================================================
# _is_table_empty
# ====================================================================


class TestIsTableEmpty:

    @patch("src.data.bulk_writer.get_session")
    def test_empty_table_returns_true(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.return_value = False
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        writer = BulkWriter()
        assert writer._is_table_empty("stocks") is True

    @patch("src.data.bulk_writer.get_session")
    def test_nonempty_table_returns_false(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.execute.return_value.scalar.return_value = True
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        writer = BulkWriter()
        assert writer._is_table_empty("stocks") is False

    @patch("src.data.bulk_writer.get_session")
    def test_exception_returns_false(self, mock_get_session):
        mock_get_session.return_value.__enter__ = MagicMock(side_effect=RuntimeError("DB error"))

        writer = BulkWriter()
        assert writer._is_table_empty("stocks") is False

    def test_rejected_table_raises(self):
        writer = BulkWriter()
        with pytest.raises(ValueError, match="not in whitelist"):
            writer._is_table_empty("evil_table")


# ====================================================================
# _batch_upsert
# ====================================================================


class TestBatchUpsert:

    @patch("src.data.bulk_writer.get_session")
    @patch("src.data.bulk_writer.sa_inspect")
    @patch("src.data.bulk_writer.insert")
    def test_upsert_with_explicit_conflict_cols(self, mock_insert, mock_inspect, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_stmt = MagicMock()
        mock_insert.return_value.values.return_value = mock_stmt
        mock_stmt.excluded = {"name": "new_name", "value": 42}
        mock_stmt.on_conflict_do_update.return_value = mock_stmt

        writer = BulkWriter(batch_size=100)
        records = [{"code": "000001", "name": "test", "value": 42}]
        result = writer._batch_upsert(
            FakeModel,
            records,
            conflict_columns=["code"],
            update_columns=["name", "value"],
        )
        assert result == 1
        mock_session.execute.assert_called_once()

    @patch("src.data.bulk_writer.get_session")
    @patch("src.data.bulk_writer.sa_inspect")
    @patch("src.data.bulk_writer.insert")
    def test_upsert_auto_detect_pk(self, mock_insert, mock_inspect, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        pk_col = MagicMock()
        pk_col.name = "code"
        mock_mapper = MagicMock()
        mock_mapper.primary_key = [pk_col]
        mock_inspect.return_value = mock_mapper

        mock_stmt = MagicMock()
        mock_insert.return_value.values.return_value = mock_stmt
        mock_stmt.excluded = {"name": "new"}
        mock_stmt.on_conflict_do_update.return_value = mock_stmt

        writer = BulkWriter()
        records = [{"code": "000001", "name": "test"}]
        result = writer._batch_upsert(FakeModel, records)
        assert result == 1
        mock_inspect.assert_called_once_with(FakeModel)

    @patch("src.data.bulk_writer.get_session")
    @patch("src.data.bulk_writer.sa_inspect")
    @patch("src.data.bulk_writer.insert")
    def test_upsert_batching(self, mock_insert, mock_inspect, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_stmt = MagicMock()
        mock_insert.return_value.values.return_value = mock_stmt
        mock_stmt.excluded = {"v": 0}
        mock_stmt.on_conflict_do_update.return_value = mock_stmt

        writer = BulkWriter(batch_size=3)
        records = [{"id": i, "v": i} for i in range(7)]
        result = writer._batch_upsert(
            FakeModel, records, conflict_columns=["id"], update_columns=["v"]
        )
        assert result == 7
        assert mock_session.execute.call_count == 3

    @patch("src.data.bulk_writer.get_session")
    @patch("src.data.bulk_writer.sa_inspect")
    @patch("src.data.bulk_writer.insert")
    def test_upsert_do_nothing_when_no_update_cols(self, mock_insert, mock_inspect, mock_get_session):
        mock_session = MagicMock()
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        mock_stmt = MagicMock()
        mock_insert.return_value.values.return_value = mock_stmt
        mock_stmt.on_conflict_do_nothing.return_value = mock_stmt

        writer = BulkWriter()
        records = [{"code": "000001"}]
        writer._batch_upsert(
            FakeModel, records, conflict_columns=["code"], update_columns=[]
        )
        mock_stmt.on_conflict_do_nothing.assert_called_once()


# ====================================================================
# write_flush
# ====================================================================


class TestWriteFlush:

    @patch.object(BulkWriter, "write", return_value=5)
    def test_groups_by_model(self, mock_write):
        writer = BulkWriter()

        class ModelA:
            __tablename__ = "a"

        class ModelB:
            __tablename__ = "b"

        batch = [
            (ModelA, [{"x": 1}]),
            (ModelB, [{"y": 2}]),
            (ModelA, [{"x": 3}]),
        ]
        writer.write_flush(batch)
        assert mock_write.call_count == 2

        call_args_list = mock_write.call_args_list
        model_record_counts = {}
        for call_args in call_args_list:
            model = call_args[0][0]
            records = call_args[0][1]
            model_record_counts[model.__tablename__] = len(records)

        assert model_record_counts["a"] == 2
        assert model_record_counts["b"] == 1

    @patch.object(BulkWriter, "write", side_effect=RuntimeError("DB error"))
    def test_write_flush_exception_logged(self, mock_write):
        writer = BulkWriter()
        batch = [(FakeModel, [{"x": 1}])]
        writer.write_flush(batch)


# ====================================================================
# write with mode selection
# ====================================================================


class TestWriteModeSelection:

    @patch.object(BulkWriter, "_copy_insert", return_value=5)
    @patch.object(BulkWriter, "_is_table_empty", return_value=True)
    def test_auto_mode_empty_table_uses_copy(self, mock_empty, mock_copy):
        writer = BulkWriter()
        writer.write(FakeModel, [{"a": 1}], mode="auto")
        mock_copy.assert_called_once()

    @patch.object(BulkWriter, "_batch_upsert", return_value=5)
    @patch.object(BulkWriter, "_is_table_empty", return_value=False)
    def test_auto_mode_nonempty_table_uses_upsert(self, mock_empty, mock_upsert):
        writer = BulkWriter()
        writer.write(FakeModel, [{"a": 1}], mode="auto")
        mock_upsert.assert_called_once()

    @patch.object(BulkWriter, "_copy_insert", return_value=5)
    def test_explicit_copy_mode(self, mock_copy):
        writer = BulkWriter()
        writer.write(FakeModel, [{"a": 1}], mode="copy")
        mock_copy.assert_called_once()

    @patch.object(BulkWriter, "_batch_upsert", return_value=5)
    def test_explicit_upsert_mode(self, mock_upsert):
        writer = BulkWriter()
        writer.write(FakeModel, [{"a": 1}], mode="upsert")
        mock_upsert.assert_called_once()
