"""Tests for src/strategy/instrument_pool.py

Mocks get_session and DB interactions to avoid PostgreSQL-specific SQL.
"""
import json
import pytest
from datetime import datetime
from unittest.mock import patch, MagicMock


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


def _make_pool_obj(
    id=1, name="test_pool", description="", codes=None,
    filter_rules=None, n_stocks=0, status="active",
    created_at=None, updated_at=None,
):
    p = MagicMock()
    p.id = id
    p.pool_name = name
    p.description = description
    p.codes_json = json.dumps(codes or [])
    p.filter_rules_json = json.dumps(filter_rules or {})
    p.n_stocks = n_stocks or len(codes or [])
    p.status = status
    p.created_at = created_at or datetime(2024, 1, 1)
    p.updated_at = updated_at or datetime(2024, 1, 1)
    return p


class TestCreatePool:

    def test_create_with_codes(self, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 10
        mock_session.execute.return_value = mock_result

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            pid = mgr.create_pool(
                name="my_pool",
                codes=["600519.SH", "000001.SZ"],
                description="test pool",
            )
        assert pid == 10
        mock_session.execute.assert_called_once()

    def test_create_with_filter_rules(self, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 20
        mock_session.execute.return_value = mock_result

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            pid = mgr.create_pool(
                name="dynamic",
                filter_rules={"sector": "沪深300"},
                description="hs300",
            )
        assert pid == 20

    def test_create_empty_pool(self, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 30
        mock_session.execute.return_value = mock_result

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            pid = mgr.create_pool(name="empty")
        assert pid == 30


class TestGetPool:

    def test_existing(self, mock_session):
        pool_obj = _make_pool_obj(name="hs300", codes=["600519.SH"])
        mock_session.query.return_value.filter_by.return_value.first.return_value = pool_obj

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            p = mgr.get_pool("hs300")

        assert p is not None
        assert p["pool_name"] == "hs300"
        assert p["codes"] == ["600519.SH"]

    def test_nonexistent(self, mock_session):
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            assert mgr.get_pool("nope") is None


class TestGetPoolCodes:

    def test_returns_codes(self, mock_session):
        pool_obj = _make_pool_obj(codes=["600519.SH", "000001.SZ"])
        mock_session.query.return_value.filter_by.return_value.first.return_value = pool_obj

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            codes = mgr.get_pool_codes("test")

        assert codes == ["600519.SH", "000001.SZ"]

    def test_nonexistent_returns_empty(self, mock_session):
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            assert mgr.get_pool_codes("ghost") == []


class TestListPools:

    def test_list_all(self, mock_session):
        p1 = _make_pool_obj(id=1, name="p1")
        p2 = _make_pool_obj(id=2, name="p2")
        query = mock_session.query.return_value
        query.order_by.return_value.all.return_value = [p1, p2]

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            result = mgr.list_pools()

        assert len(result) == 2

    def test_list_by_status(self, mock_session):
        p1 = _make_pool_obj(id=1, name="active_p", status="active")
        query = mock_session.query.return_value
        query.filter_by.return_value.order_by.return_value.all.return_value = [p1]

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            result = mgr.list_pools(status="active")

        assert len(result) == 1


class TestUpdatePoolCodes:

    def test_update(self, mock_session):
        pool_obj = _make_pool_obj(codes=["600519.SH"])
        mock_session.query.return_value.filter_by.return_value.first.return_value = pool_obj

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            mgr.update_pool_codes("test", ["600519.SH", "000001.SZ", "300750.SZ"])

        assert pool_obj.n_stocks == 3
        assert json.loads(pool_obj.codes_json) == ["600519.SH", "000001.SZ", "300750.SZ"]

    def test_update_nonexistent(self, mock_session):
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            mgr.update_pool_codes("ghost", ["000001.SZ"])


class TestRefreshDynamicPool:

    def test_refresh_with_rules(self, mock_session):
        pool_obj = _make_pool_obj(
            codes=[], filter_rules={"sector": "沪深300"},
        )
        mock_session.query.return_value.filter_by.return_value.first.return_value = pool_obj

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()

            with patch.object(mgr, "_apply_filter_rules", return_value=["600519.SH", "000001.SZ"]):
                with patch.object(mgr, "update_pool_codes"):
                    codes = mgr.refresh_dynamic_pool("hs300")

        assert "600519.SH" in codes
        assert "000001.SZ" in codes

    def test_refresh_nonexistent(self, mock_session):
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            assert mgr.refresh_dynamic_pool("ghost") == []

    def test_refresh_no_rules_returns_existing(self, mock_session):
        pool_obj = _make_pool_obj(codes=["600519.SH"], filter_rules={})
        mock_session.query.return_value.filter_by.return_value.first.return_value = pool_obj

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            codes = mgr.refresh_dynamic_pool("static")

        assert codes == ["600519.SH"]


class TestApplyFilterRules:

    def test_filter_by_sector(self, mock_session):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("300750.SZ",)]
        mock_session.execute.return_value = mock_result

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            codes = mgr._apply_filter_rules({"sector": "创业板"})

        assert codes == ["300750.SZ"]
        mock_session.execute.assert_called_once()

    def test_filter_by_market_cap_range(self, mock_session):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("000001.SZ",), ("688981.SH",)]
        mock_session.execute.return_value = mock_result

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            codes = mgr._apply_filter_rules({"min_market_cap": 2000, "max_market_cap": 5000})

        assert "000001.SZ" in codes
        assert "688981.SH" in codes

    def test_filter_builds_conditions(self, mock_session):
        """Verify that various rule keys map to SQL conditions."""
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_session.execute.return_value = mock_result

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            mgr._apply_filter_rules({
                "sector": "沪深300",
                "exchange": "SH",
                "industry": "白酒",
                "min_market_cap": 500,
                "max_market_cap": 20000,
                "min_roe": 10,
                "max_pe": 50,
            })

        call_args = mock_session.execute.call_args
        sql_text = str(call_args[0][0])
        assert "sector = :sector" in sql_text
        assert "exchange = :exchange" in sql_text
        assert "market_cap >= :min_cap" in sql_text
        assert "roe >= :min_roe" in sql_text

    def test_filter_empty_rules(self, mock_session):
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("600519.SH",), ("000001.SZ",)]
        mock_session.execute.return_value = mock_result

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager
            mgr = InstrumentPoolManager()
            codes = mgr._apply_filter_rules({})

        assert len(codes) == 2


class TestInitBuiltinPools:

    def test_creates_all_builtin(self, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 1
        mock_session.execute.return_value = mock_result

        with patch("src.strategy.instrument_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.instrument_pool import InstrumentPoolManager, BUILTIN_POOLS
            mgr = InstrumentPoolManager()
            count = mgr.init_builtin_pools()

        assert count == len(BUILTIN_POOLS)
        assert mock_session.execute.call_count == len(BUILTIN_POOLS)
