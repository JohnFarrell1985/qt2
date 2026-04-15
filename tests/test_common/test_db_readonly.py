"""Tests for get_session readonly mode"""
from unittest.mock import MagicMock, patch

from src.common.db import get_session


class TestGetSessionReadonly:
    @patch("src.common.db.get_session_factory")
    def test_readonly_does_not_commit(self, mock_factory):
        mock_session = MagicMock()
        mock_factory.return_value.return_value = mock_session

        with get_session(readonly=True) as _session:
            pass

        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()
        mock_session.close.assert_called_once()

    @patch("src.common.db.get_session_factory")
    def test_default_no_changes_does_rollback(self, mock_factory):
        mock_session = MagicMock()
        mock_session.dirty = set()
        mock_session.new = MagicMock()
        mock_session.new.__bool__ = MagicMock(return_value=False)
        mock_session.deleted = MagicMock()
        mock_session.deleted.__bool__ = MagicMock(return_value=False)
        mock_factory.return_value.return_value = mock_session

        with get_session() as _session:
            pass

        mock_session.rollback.assert_called_once()
        mock_session.commit.assert_not_called()

    @patch("src.common.db.get_session_factory")
    def test_dirty_session_commits(self, mock_factory):
        mock_session = MagicMock()
        mock_session.dirty = {"something"}
        mock_factory.return_value.return_value = mock_session

        with get_session() as _session:
            pass

        mock_session.commit.assert_called_once()

    @patch("src.common.db.get_session_factory")
    def test_exception_rolls_back(self, mock_factory):
        mock_session = MagicMock()
        mock_factory.return_value.return_value = mock_session

        try:
            with get_session() as _session:
                raise RuntimeError("test")
        except RuntimeError:
            pass

        mock_session.rollback.assert_called_once()
        mock_session.close.assert_called_once()
