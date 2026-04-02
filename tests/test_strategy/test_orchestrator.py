"""Tests for src/strategy/orchestrator.py"""
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


@pytest.fixture
def mock_macro():
    macro = MagicMock()
    macro.get_current_state.return_value = "bull"
    macro.get_state_detail.return_value = {
        "label": "牛市",
        "position_multiplier": 1.2,
        "preferred_strategies": ["momentum"],
        "avoid_strategies": ["defensive"],
    }
    macro.get_position_multiplier.return_value = 1.2
    macro.get_avoid_strategies.return_value = ["defensive"]
    return macro


@pytest.fixture
def mock_strategy_pool():
    pool = MagicMock()
    pool.get_strategy.return_value = {
        "id": 1,
        "strategy_name": "momentum_v1",
        "factor_names": ["momentum"],
        "model_path": "/models/momentum.pkl",
        "status": "active",
    }
    return pool


@pytest.fixture
def mock_instrument_pool():
    pool = MagicMock()
    pool.get_pool.return_value = {
        "id": 10,
        "pool_name": "hs300",
        "codes": ["600519.SH", "000001.SZ"],
        "status": "active",
    }
    return pool


@pytest.fixture
def orchestrator(mock_macro, mock_strategy_pool, mock_instrument_pool, mock_session):
    with patch("src.strategy.orchestrator.MacroEnvironment", return_value=mock_macro), \
         patch("src.strategy.orchestrator.StrategyPool", return_value=mock_strategy_pool), \
         patch("src.strategy.orchestrator.InstrumentPoolManager", return_value=mock_instrument_pool), \
         patch("src.strategy.orchestrator.get_session") as mock_gs:
        mock_gs.return_value = mock_session
        from src.strategy.orchestrator import StrategyOrchestrator
        orch = StrategyOrchestrator()
        orch.macro_env = mock_macro
        orch.strategy_pool = mock_strategy_pool
        orch.instrument_pool = mock_instrument_pool
        orch._mock_session = mock_session
        orch._mock_gs = mock_gs
        yield orch


class TestCreateAllocation:

    def test_create_returns_id(self, orchestrator, mock_session):
        mock_alloc = MagicMock()
        mock_alloc.id = 100
        mock_session.flush = MagicMock()

        with patch("src.strategy.orchestrator.get_session") as mock_gs:
            mock_gs.return_value = mock_session

            def side_effect_add(obj):
                obj.id = 100
            mock_session.add.side_effect = side_effect_add
            mock_session.flush.side_effect = lambda: None

            alloc_id = orchestrator.create_allocation(
                strategy_name="momentum_v1",
                pool_name="hs300",
                macro_state="bull",
                weight=0.8,
            )

        assert alloc_id == 100

    def test_missing_strategy_raises(self, orchestrator, mock_strategy_pool):
        mock_strategy_pool.get_strategy.return_value = None
        with pytest.raises(ValueError, match="策略不存在"):
            orchestrator.create_allocation("ghost_strat", "hs300")

    def test_missing_pool_raises(self, orchestrator, mock_instrument_pool):
        mock_instrument_pool.get_pool.return_value = None
        with pytest.raises(ValueError, match="标的池不存在"):
            orchestrator.create_allocation("momentum_v1", "ghost_pool")


class TestGetActiveAllocations:

    def _make_alloc(self, id=1, strategy_id=1, pool_id=10, macro_state="bull",
                    weight=1.0, is_active="true"):
        alloc = MagicMock()
        alloc.id = id
        alloc.strategy_id = strategy_id
        alloc.pool_id = pool_id
        alloc.macro_state = macro_state
        alloc.weight = weight
        alloc.is_active = is_active
        return alloc

    def test_returns_allocations(self, orchestrator, mock_session):
        alloc = self._make_alloc()

        strat = MagicMock()
        strat.id = 1
        strat.strategy_name = "momentum_v1"
        strat.factor_names_json = json.dumps(["momentum"])
        strat.model_path = "/models/m.pkl"

        pool = MagicMock()
        pool.id = 10
        pool.pool_name = "hs300"
        pool.codes_json = json.dumps(["600519.SH"])

        with patch("src.strategy.orchestrator.get_session") as mock_gs:
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            mock_gs.return_value = session

            q = session.query.return_value
            q.filter_by.return_value.all.return_value = [alloc]
            session.query.return_value.filter_by.return_value.first.side_effect = [
                strat, pool,
            ]

            result = orchestrator.get_active_allocations(macro_state="bull")

        assert len(result) == 1
        assert result[0]["strategy_name"] == "momentum_v1"

    def test_filters_by_macro_state(self, orchestrator, mock_session):
        alloc = self._make_alloc(macro_state="bull")

        with patch("src.strategy.orchestrator.get_session") as mock_gs:
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            mock_gs.return_value = session

            q = session.query.return_value
            q.filter_by.return_value.all.return_value = [alloc]

            result = orchestrator.get_active_allocations(macro_state="bear")

        assert len(result) == 0

    def test_empty_macro_matches_all(self, orchestrator, mock_session):
        alloc = self._make_alloc(macro_state="")

        strat = MagicMock()
        strat.id = 1
        strat.strategy_name = "s1"
        strat.factor_names_json = json.dumps(["x"])
        strat.model_path = ""

        pool = MagicMock()
        pool.id = 10
        pool.pool_name = "p1"
        pool.codes_json = json.dumps(["600519.SH"])

        with patch("src.strategy.orchestrator.get_session") as mock_gs:
            session = MagicMock()
            session.__enter__ = MagicMock(return_value=session)
            session.__exit__ = MagicMock(return_value=False)
            mock_gs.return_value = session

            q = session.query.return_value
            q.filter_by.return_value.all.return_value = [alloc]
            session.query.return_value.filter_by.return_value.first.side_effect = [
                strat, pool,
            ]

            result = orchestrator.get_active_allocations(macro_state="bear")

        assert len(result) == 1


class TestGetCurrentPlan:

    def test_plan_structure(self, orchestrator):
        with patch.object(orchestrator, "get_active_allocations", return_value=[
            {
                "allocation_id": 1,
                "strategy_name": "momentum_v1",
                "strategy_id": 1,
                "factor_names": ["momentum"],
                "model_path": "/m.pkl",
                "pool_name": "hs300",
                "pool_codes": ["600519.SH"],
                "macro_state": "bull",
                "weight": 0.8,
            },
        ]):
            plan = orchestrator.get_current_plan()

        assert plan["macro_state"] == "bull"
        assert plan["position_multiplier"] == pytest.approx(1.2)
        assert plan["n_strategies"] == 1
        assert len(plan["allocations"]) == 1
        assert plan["allocations"][0]["adjusted_weight"] == pytest.approx(0.8 * 1.2)

    def test_avoids_strategies(self, orchestrator):
        with patch.object(orchestrator, "get_active_allocations", return_value=[
            {
                "allocation_id": 1,
                "strategy_name": "momentum_v1",
                "weight": 0.5,
            },
            {
                "allocation_id": 2,
                "strategy_name": "defensive",
                "weight": 0.5,
            },
        ]):
            plan = orchestrator.get_current_plan()

        names = [a["strategy_name"] for a in plan["allocations"]]
        assert "defensive" not in names
        assert "momentum_v1" in names

    def test_plan_empty_allocations(self, orchestrator):
        with patch.object(orchestrator, "get_active_allocations", return_value=[]):
            plan = orchestrator.get_current_plan()

        assert plan["n_strategies"] == 0
        assert plan["allocations"] == []


class TestDeactivateAllocation:

    def test_deactivate(self, orchestrator, mock_session):
        alloc = MagicMock()
        alloc.is_active = "true"

        with patch("src.strategy.orchestrator.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            mock_session.query.return_value.filter_by.return_value.first.return_value = alloc
            orchestrator.deactivate_allocation(1)

        assert alloc.is_active == "false"

    def test_deactivate_nonexistent(self, orchestrator, mock_session):
        with patch("src.strategy.orchestrator.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            mock_session.query.return_value.filter_by.return_value.first.return_value = None
            orchestrator.deactivate_allocation(99999)
