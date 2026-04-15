"""Tests for version-related methods in src/factor/factor_pool.py."""
from datetime import datetime

import pytest
from unittest.mock import patch, MagicMock

from src.factor.factor_pool import FactorPool


def _make_factor_meta(factor_id, factor_name, version, category="tech", description="", data_source="calculated"):
    """Create a mock FactorMeta row."""
    m = MagicMock()
    m.factor_id = factor_id
    m.factor_name = factor_name
    m.version = version
    m.category = category
    m.description = description
    m.data_source = data_source
    m.created_at = datetime(2026, 1, 1)
    return m


class TestGetVersions:
    @pytest.mark.timeout(30)
    @patch("src.factor.factor_pool.get_session")
    def test_returns_list_of_versions(self, mock_gs):
        rows = [
            _make_factor_meta(1, "momentum_20d", 1, description="v1"),
            _make_factor_meta(5, "momentum_20d", 2, description="v2"),
        ]
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
        mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)

        pool = FactorPool()
        result = pool.get_versions("momentum_20d")

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["version"] == 1
        assert result[1]["version"] == 2
        assert result[0]["factor_id"] == 1

    @pytest.mark.timeout(30)
    @patch("src.factor.factor_pool.get_session")
    def test_empty_when_no_versions(self, mock_gs):
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
        mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)

        pool = FactorPool()
        result = pool.get_versions("nonexistent_factor")
        assert result == []


class TestRegisterNewVersion:
    @pytest.mark.timeout(30)
    @patch("src.factor.factor_pool.get_session")
    def test_creates_new_version(self, mock_gs):
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.scalar.return_value = 2

        def flush_side_effect():
            for call in mock_session.add.call_args_list:
                call[0][0].factor_id = 99

        mock_session.flush.side_effect = flush_side_effect
        mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)

        pool = FactorPool()
        fid = pool.register_new_version(
            "rsi_14", category="tech", description="improved RSI",
        )
        assert fid == 99
        mock_session.add.assert_called_once()
        added = mock_session.add.call_args[0][0]
        assert added.factor_name == "rsi_14"
        assert added.version == 3

    @pytest.mark.timeout(30)
    @patch("src.factor.factor_pool.get_session")
    def test_first_version_when_none_exists(self, mock_gs):
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.scalar.return_value = 0

        def flush_side_effect():
            for call in mock_session.add.call_args_list:
                call[0][0].factor_id = 1

        mock_session.flush.side_effect = flush_side_effect
        mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)

        pool = FactorPool()
        fid = pool.register_new_version("new_factor")
        assert fid == 1
        added = mock_session.add.call_args[0][0]
        assert added.version == 1


class TestListFactorsVersion:
    @pytest.mark.timeout(30)
    @patch("src.factor.factor_pool.get_session")
    def test_latest_only_deduplicates(self, mock_gs):
        rows = [
            _make_factor_meta(1, "momentum_20d", 1),
            _make_factor_meta(5, "momentum_20d", 2),
            _make_factor_meta(10, "rsi_14", 1),
        ]
        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = rows
        mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)

        pool = FactorPool()
        result = pool.list_factors(latest_only=True)

        assert len(result) == 2
        names = {r["factor_name"] for r in result}
        assert names == {"momentum_20d", "rsi_14"}
        mom = [r for r in result if r["factor_name"] == "momentum_20d"][0]
        assert mom["version"] == 2

    @pytest.mark.timeout(30)
    @patch("src.factor.factor_pool.get_session")
    def test_all_versions(self, mock_gs):
        rows = [
            _make_factor_meta(1, "momentum_20d", 1),
            _make_factor_meta(5, "momentum_20d", 2),
        ]
        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = rows
        mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)

        pool = FactorPool()
        result = pool.list_factors(latest_only=False)
        assert len(result) == 2

    @pytest.mark.timeout(30)
    @patch("src.factor.factor_pool.get_session")
    def test_category_filter(self, mock_gs):
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.all.return_value = []
        mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)

        pool = FactorPool()
        result = pool.list_factors(category="tech")
        assert result == []


class TestGetFactorIdVersion:
    @pytest.mark.timeout(30)
    @patch("src.factor.factor_pool.get_session")
    def test_specific_version(self, mock_gs):
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.filter.return_value.first.return_value = (42,)
        mock_gs.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)

        pool = FactorPool()
        pool._meta_cache = {"some_other": 99}
        fid = pool.get_factor_id("momentum_20d", version=2)
        assert fid == 42

    @pytest.mark.timeout(30)
    def test_from_cache_when_no_version(self):
        pool = FactorPool()
        pool._meta_cache = {"rsi_14": 10, "momentum_20d": 5}
        assert pool.get_factor_id("rsi_14") == 10
        assert pool.get_factor_id("nonexistent") is None
