"""Tests for src/ml/ensemble.py - EnsembleFactorModel"""
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def index_10():
    return pd.RangeIndex(10)


@pytest.fixture
def mock_sub_model(index_10):
    """Return a factory that creates a mock model with given predictions."""
    def _make(values: np.ndarray):
        m = MagicMock()
        m.predict.return_value = pd.Series(values, index=index_10, name="predicted_return")
        m.train.return_value = {"model_type": "mock", "n_features": 3, "n_samples": 100}
        m.get_feature_importance.return_value = pd.Series(
            [0.5, 0.3, 0.2], index=["f0", "f1", "f2"],
        )
        return m
    return _make


class TestRankAveraging:
    @pytest.mark.timeout(30)
    def test_rank_avg_with_mocked_models(self, mock_sub_model, index_10):
        from src.ml.ensemble import EnsembleFactorModel

        rng = np.random.RandomState(42)
        model_a = mock_sub_model(rng.randn(10))
        model_b = mock_sub_model(rng.randn(10))
        model_c = mock_sub_model(rng.randn(10))

        ens = EnsembleFactorModel(method="rank_avg", weights=[1.0, 1.0, 1.0])
        ens.models = {"lgb": model_a, "xgb": model_b, "catboost": model_c}
        ens._available_models = ["lgb", "xgb", "catboost"]

        X = pd.DataFrame({"f0": rng.randn(10)}, index=index_10)
        preds = ens.predict(X)

        assert isinstance(preds, pd.Series)
        assert preds.name == "predicted_return"
        assert len(preds) == 10
        assert preds.min() >= 0.0
        assert preds.max() <= 1.0

    @pytest.mark.timeout(30)
    def test_weighted_rank_avg(self, mock_sub_model, index_10):
        from src.ml.ensemble import EnsembleFactorModel

        vals = np.arange(10, dtype=float)
        model_a = mock_sub_model(vals)
        model_b = mock_sub_model(vals[::-1])

        ens = EnsembleFactorModel(method="rank_avg", weights=[2.0, 1.0])
        ens.models = {"lgb": model_a, "xgb": model_b}

        X = pd.DataFrame({"f0": np.zeros(10)}, index=index_10)
        preds = ens.predict(X)
        assert isinstance(preds, pd.Series)
        assert len(preds) == 10


class TestLazyInit:
    @pytest.mark.timeout(30)
    def test_models_initialized_lazily(self):
        from src.ml.ensemble import EnsembleFactorModel

        ens = EnsembleFactorModel()
        assert ens.models == {}
        assert ens._available_models == []

    @pytest.mark.timeout(30)
    def test_predict_before_train_raises(self):
        from src.ml.ensemble import EnsembleFactorModel

        ens = EnsembleFactorModel()
        X = pd.DataFrame({"f0": [1.0, 2.0]})
        with pytest.raises(ValueError, match="模型未训练"):
            ens.predict(X)


class TestPartialAvailability:
    @pytest.mark.timeout(30)
    def test_only_lgb_available(self, mock_sub_model, index_10):
        """Simulate XGB/CatBoost not importable — only LGB works."""
        from src.ml.ensemble import EnsembleFactorModel

        rng = np.random.RandomState(99)
        lgb_model = mock_sub_model(rng.randn(10))

        ens = EnsembleFactorModel(method="rank_avg")
        ens.models = {"lgb": lgb_model}
        ens._available_models = ["lgb"]

        X = pd.DataFrame({"f0": rng.randn(10)}, index=index_10)
        preds = ens.predict(X)
        assert isinstance(preds, pd.Series)
        assert len(preds) == 10


class TestTrain:
    @pytest.mark.timeout(30)
    def test_train_calls_submodels(self, mock_sub_model):
        from src.ml.ensemble import EnsembleFactorModel

        rng = np.random.RandomState(0)
        model_a = mock_sub_model(rng.randn(10))
        model_b = mock_sub_model(rng.randn(10))

        ens = EnsembleFactorModel()
        ens.models = {"lgb": model_a, "xgb": model_b}
        ens._available_models = ["lgb", "xgb"]

        X = pd.DataFrame({"f0": rng.randn(100)})
        y = pd.Series(rng.randn(100))

        result = ens.train(X, y)
        assert result["ensemble_method"] == "rank_avg"
        assert result["n_models"] == 2
        model_a.train.assert_called_once()
        model_b.train.assert_called_once()


class TestFeatureImportance:
    @pytest.mark.timeout(30)
    def test_combined_importance(self, mock_sub_model):
        from src.ml.ensemble import EnsembleFactorModel

        rng = np.random.RandomState(0)
        model_a = mock_sub_model(rng.randn(10))
        model_b = mock_sub_model(rng.randn(10))

        ens = EnsembleFactorModel()
        ens.models = {"lgb": model_a, "xgb": model_b}

        imp = ens.get_feature_importance(top_n=3)
        assert isinstance(imp, pd.DataFrame)
        assert "lgb" in imp.columns
        assert "xgb" in imp.columns
