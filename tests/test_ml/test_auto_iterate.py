"""Tests for src/ml/auto_iterate.py - AutoIterateEngine, IterationRecord"""
import numpy as np
import pandas as pd
import pytest
from copy import deepcopy
from datetime import date
from unittest.mock import patch, MagicMock

from src.ml.auto_iterate import AutoIterateEngine, IterationRecord
from src.ml.lgb_model import LGBFactorModel


# ---------------------------------------------------------------------------
# IterationRecord
# ---------------------------------------------------------------------------

class TestIterationRecord:
    def test_default_values(self):
        r = IterationRecord()
        assert r.iteration == 0
        assert r.factor_names == []
        assert r.params == {}
        assert r.score == 0.0

    def test_to_dict(self):
        r = IterationRecord()
        r.iteration = 3
        r.factor_names = ["f1", "f2"]
        r.params = {"num_leaves": 31}
        r.train_metrics = {"val_mse": 0.001}
        r.backtest_metrics = {"ic_mean": 0.05}
        r.score = 1.23
        r.timestamp = "2024-06-01T12:00:00"

        d = r.to_dict()
        assert d["iteration"] == 3
        assert d["n_factors"] == 2
        assert d["factor_names"] == ["f1", "f2"]
        assert d["params"] == {"num_leaves": 31}
        assert d["score"] == 1.23
        assert d["timestamp"] == "2024-06-01T12:00:00"


# ---------------------------------------------------------------------------
# _composite_score
# ---------------------------------------------------------------------------

class TestCompositeScore:
    def test_formula(self):
        score = AutoIterateEngine._composite_score(ic_mean=0.05, icir=1.5, long_short=0.02)
        expected = abs(0.05) * 0.3 + abs(1.5) * 0.4 + abs(0.02) * 100 * 0.3
        assert abs(score - expected) < 1e-9

    def test_negative_values_use_abs(self):
        score = AutoIterateEngine._composite_score(ic_mean=-0.05, icir=-1.5, long_short=-0.02)
        expected = 0.05 * 0.3 + 1.5 * 0.4 + 2.0 * 0.3
        assert abs(score - expected) < 1e-9

    def test_zeros(self):
        assert AutoIterateEngine._composite_score(0, 0, 0) == 0.0


# ---------------------------------------------------------------------------
# _evolve
# ---------------------------------------------------------------------------

class TestEvolve:
    @pytest.fixture
    def engine(self):
        return AutoIterateEngine(
            all_factor_names=[f"f{i}" for i in range(20)],
            stock_pool=["000001"],
            train_start=date(2023, 1, 1),
            train_end=date(2024, 12, 31),
            test_start=date(2025, 1, 1),
            test_end=date(2025, 12, 31),
            min_factors=5,
        )

    def test_drops_low_importance(self, engine):
        record = IterationRecord()
        record.backtest_metrics = {
            "feature_importance": {"f0": 100, "f1": 50, "f2": 30, "f3": 10, "f4": 5, "f5": 1},
        }
        current = ["f0", "f1", "f2", "f3", "f4", "f5"]
        new_factors, _ = engine._evolve(1, current, {}, record)
        assert "f5" not in new_factors

    def test_adds_back_when_below_min(self, engine):
        record = IterationRecord()
        record.backtest_metrics = {
            "feature_importance": {"f0": 10, "f1": 5, "f2": 1, "f3": 0.5},
        }
        current = ["f0", "f1", "f2", "f3"]
        new_factors, _ = engine._evolve(1, current, {}, record)
        assert len(new_factors) >= engine.min_factors

    def test_explores_new_factors_at_mod3(self, engine):
        record = IterationRecord()
        record.backtest_metrics = {"feature_importance": {"f0": 100, "f1": 50, "f2": 30,
                                                          "f3": 20, "f4": 10}}
        current = ["f0", "f1", "f2", "f3", "f4"]
        new_factors, _ = engine._evolve(3, current, {}, record)
        assert len(new_factors) >= len(current)

    def test_tunes_params_at_mod5(self, engine):
        record = IterationRecord()
        record.backtest_metrics = {"feature_importance": {"f0": 100, "f1": 50, "f2": 30,
                                                          "f3": 20, "f4": 10}}
        current = ["f0", "f1", "f2", "f3", "f4"]
        params = deepcopy(LGBFactorModel.DEFAULT_PARAMS)
        _, new_params = engine._evolve(5, current, params, record)
        assert new_params["num_leaves"] in [31, 47, 63, 95, 127]
        assert new_params["learning_rate"] in [0.01, 0.03, 0.05, 0.08, 0.1]

    def test_no_importance_no_crash(self, engine):
        record = IterationRecord()
        record.backtest_metrics = {}
        current = ["f0", "f1", "f2", "f3", "f4", "f5"]
        new_factors, new_params = engine._evolve(1, current, {}, record)
        assert isinstance(new_factors, list)
        assert isinstance(new_params, dict)


# ---------------------------------------------------------------------------
# get_convergence_curve / get_factor_frequency
# ---------------------------------------------------------------------------

class TestAnalytics:
    @pytest.fixture
    def engine_with_history(self):
        engine = AutoIterateEngine(
            all_factor_names=["f1", "f2", "f3"],
            stock_pool=["000001"],
            train_start=date(2023, 1, 1),
            train_end=date(2024, 12, 31),
            test_start=date(2025, 1, 1),
            test_end=date(2025, 12, 31),
        )
        for i in range(1, 4):
            r = IterationRecord()
            r.iteration = i
            r.factor_names = ["f1", "f2"] if i <= 2 else ["f1", "f3"]
            r.score = i * 0.5
            r.backtest_metrics = {"ic_mean": 0.03 * i, "icir": 0.5 * i}
            engine.history.append(r)
        return engine

    def test_convergence_curve_shape(self, engine_with_history):
        df = engine_with_history.get_convergence_curve()
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 3
        assert "iteration" in df.columns
        assert "score" in df.columns
        assert "best_score" in df.columns

    def test_best_score_monotonic(self, engine_with_history):
        df = engine_with_history.get_convergence_curve()
        assert (df["best_score"].diff().dropna() >= 0).all()

    def test_factor_frequency(self, engine_with_history):
        freq = engine_with_history.get_factor_frequency()
        assert isinstance(freq, pd.Series)
        assert freq["f1"] == 3
        assert freq["f2"] == 2
        assert freq["f3"] == 1

    def test_empty_history(self):
        engine = AutoIterateEngine(
            all_factor_names=[], stock_pool=[],
            train_start=date(2023, 1, 1), train_end=date(2024, 12, 31),
            test_start=date(2025, 1, 1), test_end=date(2025, 12, 31),
        )
        df = engine.get_convergence_curve()
        assert len(df) == 0
        freq = engine.get_factor_frequency()
        assert len(freq) == 0


# ---------------------------------------------------------------------------
# Full run integration (mocked)
# ---------------------------------------------------------------------------

class TestRun:
    @patch("src.ml.auto_iterate.get_session")
    @patch("src.ml.auto_iterate.evaluate_predictions")
    @patch("src.ml.auto_iterate.LGBFactorModel")
    @patch("src.ml.auto_iterate.FactorDataset")
    @patch("src.ml.auto_iterate.FactorSelector")
    def test_run_2_iterations(self, MockSelector, MockDataset, MockModel,
                              mock_eval, mock_session):
        rng = np.random.RandomState(0)
        n = 100
        dates = pd.bdate_range("2023-01-01", periods=20)
        codes = [f"{i:06d}" for i in range(1, 6)]
        index = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])

        X = pd.DataFrame({"f1": rng.randn(n), "f2": rng.randn(n), "f3": rng.randn(n)}, index=index)
        y = pd.Series(rng.randn(n) * 0.01, index=index)

        mock_ds = MockDataset.return_value
        mock_ds.build.return_value = (X, y)
        mock_ds.train_val_test_split.return_value = {
            "X_train": X.iloc[:60], "y_train": y.iloc[:60],
            "X_val": X.iloc[60:80], "y_val": y.iloc[60:80],
            "X_test": X.iloc[80:], "y_test": y.iloc[80:],
            "train_end": dates[12], "val_end": dates[16],
        }

        mock_mdl = MockModel.return_value
        mock_mdl.train.return_value = {"n_features": 3, "n_samples": 60, "val_mse": 0.001, "val_ic": 0.05}
        mock_mdl.predict.return_value = pd.Series(rng.randn(20) * 0.01, index=X.iloc[80:].index)
        mock_mdl.get_feature_importance.return_value = pd.Series({"f1": 100, "f2": 50, "f3": 20})

        mock_eval.return_value = {
            "ic_mean": 0.05, "icir": 1.2, "long_short_return": 0.02,
            "overall_ic": 0.04, "ic_std": 0.04, "group_returns": {},
            "n_samples": 20, "n_periods": 4,
        }

        mock_selector = MockSelector.return_value
        mock_selector.select_top_factors.return_value = ["f1", "f2", "f3"]
        mock_selector.correlation_filter.return_value = ["f1", "f2", "f3"]

        mock_sess = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_sess)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        engine = AutoIterateEngine(
            all_factor_names=["f1", "f2", "f3"],
            stock_pool=["000001", "000002"],
            train_start=date(2023, 1, 1),
            train_end=date(2024, 12, 31),
            test_start=date(2025, 1, 1),
            test_end=date(2025, 12, 31),
            initial_top_n=3,
            min_factors=2,
        )
        engine._save_best_model = MagicMock()

        best = engine.run(max_iterations=2, convergence_patience=5)
        assert isinstance(best, IterationRecord)
        assert best.score > 0
        assert len(engine.history) == 2

    @patch("src.ml.auto_iterate.get_session")
    @patch("src.ml.auto_iterate.evaluate_predictions")
    @patch("src.ml.auto_iterate.LGBFactorModel")
    @patch("src.ml.auto_iterate.FactorDataset")
    @patch("src.ml.auto_iterate.FactorSelector")
    def test_early_stop_on_sharpe(self, MockSelector, MockDataset, MockModel,
                                  mock_eval, mock_session):
        rng = np.random.RandomState(1)
        n = 100
        dates = pd.bdate_range("2023-01-01", periods=20)
        codes = [f"{i:06d}" for i in range(1, 6)]
        index = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])
        X = pd.DataFrame({"f1": rng.randn(n)}, index=index)
        y = pd.Series(rng.randn(n), index=index)

        mock_ds = MockDataset.return_value
        mock_ds.build.return_value = (X, y)
        mock_ds.train_val_test_split.return_value = {
            "X_train": X.iloc[:60], "y_train": y.iloc[:60],
            "X_val": X.iloc[60:80], "y_val": y.iloc[60:80],
            "X_test": X.iloc[80:], "y_test": y.iloc[80:],
            "train_end": dates[12], "val_end": dates[16],
        }

        mock_mdl = MockModel.return_value
        mock_mdl.train.return_value = {"n_features": 1, "n_samples": 60}
        mock_mdl.predict.return_value = pd.Series(rng.randn(20), index=X.iloc[80:].index)
        mock_mdl.get_feature_importance.return_value = pd.Series({"f1": 100})

        mock_eval.return_value = {
            "ic_mean": 0.1, "icir": 2.5, "long_short_return": 0.05,
            "overall_ic": 0.1, "ic_std": 0.04, "group_returns": {},
            "n_samples": 20, "n_periods": 4,
        }

        mock_selector = MockSelector.return_value
        mock_selector.select_top_factors.return_value = ["f1"]
        mock_selector.correlation_filter.return_value = ["f1"]

        mock_sess = MagicMock()
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_sess)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        engine = AutoIterateEngine(
            all_factor_names=["f1"],
            stock_pool=["000001"],
            train_start=date(2023, 1, 1),
            train_end=date(2024, 12, 31),
            test_start=date(2025, 1, 1),
            test_end=date(2025, 12, 31),
            min_factors=1,
        )

        engine._run_single_iteration = MagicMock()
        record = IterationRecord()
        record.iteration = 1
        record.score = 2.0
        record.factor_names = ["f1"]
        record.backtest_metrics = {"sharpe_ratio": 3.0, "ic_mean": 0.1, "icir": 2.5,
                                   "feature_importance": {"f1": 100}}
        record.train_metrics = {}
        record.params = {}
        record.timestamp = ""
        engine._run_single_iteration.return_value = record
        engine._initial_factor_selection = MagicMock(return_value=["f1"])
        engine._save_best_model = MagicMock()
        engine._log_to_db = MagicMock()
        engine._log_final_report = MagicMock()

        best = engine.run(max_iterations=10, target_sharpe=2.0)
        assert len(engine.history) == 1
