"""Tests for src/strategy/strategy_pool.py

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


def _make_strategy_obj(
    id=1, name="alpha_v1", description="test", factor_names=None,
    factor_weights=None, model_params=None, model_path="",
    backtest_sharpe=None, backtest_annual_return=None,
    backtest_max_drawdown=None, ic_mean=None, icir=None,
    status="active", applicable_macro="", created_at=None, updated_at=None,
    strategy_tier="ml", strategy_class="", config=None,
):
    s = MagicMock()
    s.id = id
    s.strategy_name = name
    s.strategy_tier = strategy_tier
    s.strategy_class = strategy_class
    s.config_json = json.dumps(config or {})
    s.description = description
    s.factor_names_json = json.dumps(factor_names or ["momentum", "value"])
    s.factor_weights_json = json.dumps(factor_weights or {"momentum": 0.6})
    s.model_params_json = json.dumps(model_params or {})
    s.model_path = model_path
    s.backtest_sharpe = backtest_sharpe
    s.backtest_annual_return = backtest_annual_return
    s.backtest_max_drawdown = backtest_max_drawdown
    s.ic_mean = ic_mean
    s.icir = icir
    s.status = status
    s.applicable_macro = applicable_macro
    s.created_at = created_at or datetime(2024, 1, 1)
    s.updated_at = updated_at or datetime(2024, 1, 1)
    return s


class TestCreateStrategy:

    def test_create_returns_id(self, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 42
        mock_session.execute.return_value = mock_result

        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()
            sid = pool.create_strategy(
                name="alpha_v1",
                factor_names=["momentum", "value"],
                description="test",
            )
        assert sid == 42

    def test_create_with_all_params(self, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 1
        mock_session.execute.return_value = mock_result

        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()
            sid = pool.create_strategy(
                name="full_strat",
                factor_names=["momentum", "value", "size"],
                factor_weights={"momentum": 0.5, "value": 0.3, "size": 0.2},
                model_params={"n_estimators": 200, "learning_rate": 0.05},
                description="full params test",
                applicable_macro=["bull", "range_bound"],
            )
        assert sid == 1
        mock_session.execute.assert_called_once()

    def test_applicable_macro_joined(self, mock_session):
        mock_result = MagicMock()
        mock_result.scalar_one.return_value = 10
        mock_session.execute.return_value = mock_result

        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()
            pool.create_strategy(
                name="macro_strat",
                factor_names=["x"],
                applicable_macro=["bull", "bear"],
            )
        mock_session.execute.assert_called_once()


class TestUpdateBacktestMetrics:

    def test_update_metrics(self, mock_session):
        strat = _make_strategy_obj()
        mock_session.query.return_value.filter_by.return_value.first.return_value = strat

        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()
            pool.update_backtest_metrics(
                "alpha_v1", sharpe=1.5, annual_return=0.25,
                max_drawdown=-0.12, ic_mean=0.05, icir=1.2,
                model_path="/models/alpha.pkl",
            )

        assert strat.backtest_sharpe == 1.5
        assert strat.backtest_annual_return == 0.25
        assert strat.backtest_max_drawdown == -0.12
        assert strat.ic_mean == 0.05
        assert strat.icir == 1.2
        assert strat.model_path == "/models/alpha.pkl"

    def test_update_nonexistent_does_nothing(self, mock_session):
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()
            pool.update_backtest_metrics("ghost", sharpe=1.0, annual_return=0.1, max_drawdown=-0.1)

    def test_update_without_model_path(self, mock_session):
        strat = _make_strategy_obj(model_path="/old/path.pkl")
        mock_session.query.return_value.filter_by.return_value.first.return_value = strat

        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()
            pool.update_backtest_metrics("alpha_v1", sharpe=2.0, annual_return=0.3, max_drawdown=-0.05)

        assert strat.model_path == "/old/path.pkl"


class TestListStrategies:

    def test_list_all(self, mock_session):
        s1 = _make_strategy_obj(id=1, name="s1")
        s2 = _make_strategy_obj(id=2, name="s2")
        query = mock_session.query.return_value
        query.order_by.return_value.all.return_value = [s1, s2]

        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()
            result = pool.list_strategies()

        assert len(result) == 2
        assert result[0]["strategy_name"] == "s1"

    def test_list_by_status(self, mock_session):
        s1 = _make_strategy_obj(id=1, name="active_s", status="active")
        query = mock_session.query.return_value
        query.filter_by.return_value.order_by.return_value.all.return_value = [s1]

        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()
            result = pool.list_strategies(status="active")

        assert len(result) == 1
        assert result[0]["status"] == "active"

    def test_list_empty(self, mock_session):
        query = mock_session.query.return_value
        query.order_by.return_value.all.return_value = []

        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()
            result = pool.list_strategies()
        assert result == []


class TestGetStrategy:

    def test_get_existing(self, mock_session):
        s = _make_strategy_obj(id=5, name="alpha_v1")
        mock_session.query.return_value.filter_by.return_value.first.return_value = s

        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()
            result = pool.get_strategy("alpha_v1")

        assert result is not None
        assert result["id"] == 5
        assert result["strategy_name"] == "alpha_v1"
        assert result["factor_names"] == ["momentum", "value"]

    def test_get_nonexistent(self, mock_session):
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()
            assert pool.get_strategy("nope") is None


class TestSetStatus:

    def test_set_status(self, mock_session):
        s = _make_strategy_obj(status="active")
        mock_session.query.return_value.filter_by.return_value.first.return_value = s

        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()
            pool.set_status("alpha_v1", "archived")

        assert s.status == "archived"

    def test_set_status_nonexistent(self, mock_session):
        mock_session.query.return_value.filter_by.return_value.first.return_value = None

        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()
            pool.set_status("ghost", "paused")


class TestGetStrategiesForMacro:

    def test_returns_matching(self, mock_session):
        s_bull = _make_strategy_obj(id=1, name="s_bull", applicable_macro="bull")
        s_bear = _make_strategy_obj(id=2, name="s_bear", applicable_macro="bear")
        s_any = _make_strategy_obj(id=3, name="s_any", applicable_macro="")

        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()

            with patch.object(pool, "list_strategies", return_value=[
                {"strategy_name": "s_bull", "applicable_macro": "bull"},
                {"strategy_name": "s_bear", "applicable_macro": "bear"},
                {"strategy_name": "s_any", "applicable_macro": ""},
            ]):
                result = pool.get_strategies_for_macro("bull")

        names = [s["strategy_name"] for s in result]
        assert "s_bull" in names
        assert "s_any" in names
        assert "s_bear" not in names

    def test_empty_macro_returns_all(self, mock_session):
        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()

            with patch.object(pool, "list_strategies", return_value=[
                {"strategy_name": "s1", "applicable_macro": ""},
                {"strategy_name": "s2", "applicable_macro": ""},
            ]):
                result = pool.get_strategies_for_macro("anything")
        assert len(result) == 2


class TestRankStrategies:

    def test_rank_by_sharpe(self, mock_session):
        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()

            with patch.object(pool, "list_strategies", return_value=[
                {"strategy_name": "low", "backtest_sharpe": 0.5, "status": "active"},
                {"strategy_name": "high", "backtest_sharpe": 2.0, "status": "active"},
            ]):
                df = pool.rank_strategies(metric="backtest_sharpe")

        assert len(df) == 2
        assert df.iloc[0]["strategy_name"] == "high"

    def test_rank_empty(self, mock_session):
        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()

            with patch.object(pool, "list_strategies", return_value=[]):
                df = pool.rank_strategies()
        assert len(df) == 0

    def test_rank_unknown_metric(self, mock_session):
        with patch("src.strategy.strategy_pool.get_session") as mock_gs:
            mock_gs.return_value = mock_session
            from src.strategy.strategy_pool import StrategyPool
            pool = StrategyPool()

            with patch.object(pool, "list_strategies", return_value=[
                {"strategy_name": "s1", "backtest_sharpe": 1.0},
            ]):
                df = pool.rank_strategies(metric="nonexistent_column")
        assert len(df) == 1
