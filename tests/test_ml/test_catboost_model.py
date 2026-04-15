"""Tests for src/ml/catboost_model.py - CatBoostFactorModel"""
import numpy as np
import pandas as pd
import pytest

catboost = pytest.importorskip("catboost")

from src.ml.catboost_model import CatBoostFactorModel


@pytest.fixture
def synthetic_data():
    """100 rows, 10 features, MultiIndex(trade_date, code)."""
    rng = np.random.RandomState(42)
    n_dates = 10
    n_stocks = 10
    dates = pd.bdate_range("2024-01-01", periods=n_dates)
    codes = [f"{i:06d}" for i in range(1, n_stocks + 1)]
    index = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])

    features = {f"f{i}": rng.randn(len(index)) for i in range(10)}
    X = pd.DataFrame(features, index=index)
    y = pd.Series(rng.randn(len(index)) * 0.01, index=index, name="forward_return")
    return X, y


@pytest.fixture
def small_params():
    return {
        "iterations": 20,
        "depth": 3,
        "verbose": 0,
        "random_seed": 42,
        "boosting_type": "Plain",
    }


@pytest.fixture
def model(small_params):
    return CatBoostFactorModel(params=small_params)


class TestInit:
    @pytest.mark.timeout(30)
    def test_default_params(self):
        m = CatBoostFactorModel()
        assert m.params["loss_function"] == "RMSE"
        assert m.params["boosting_type"] == "Ordered"
        assert m.model is None
        assert m.feature_names == []
        assert m.feature_importance_ is None

    @pytest.mark.timeout(30)
    def test_custom_params_override(self):
        m = CatBoostFactorModel(params={"depth": 4, "learning_rate": 0.1})
        assert m.params["depth"] == 4
        assert m.params["learning_rate"] == 0.1
        assert m.params["loss_function"] == "RMSE"


class TestTrain:
    @pytest.mark.timeout(30)
    def test_train_without_validation(self, model, synthetic_data):
        X, y = synthetic_data
        metrics = model.train(X, y)
        assert metrics["model_type"] == "catboost"
        assert metrics["n_features"] == 10
        assert metrics["n_samples"] == 100
        assert "best_iteration" in metrics
        assert "val_mse" not in metrics
        assert model.model is not None
        assert model.feature_names == list(X.columns)
        assert model.feature_importance_ is not None

    @pytest.mark.timeout(30)
    def test_train_with_validation(self, model, synthetic_data):
        X, y = synthetic_data
        split = 80
        metrics = model.train(
            X.iloc[:split], y.iloc[:split],
            X.iloc[split:], y.iloc[split:],
            stopping_rounds=5,
        )
        assert "val_mse" in metrics
        assert "val_ic" in metrics
        assert isinstance(metrics["val_mse"], float)
        assert metrics["val_mse"] >= 0

    @pytest.mark.timeout(30)
    def test_feature_importance_sorted_descending(self, model, synthetic_data):
        X, y = synthetic_data
        model.train(X, y)
        imp = model.feature_importance_
        assert list(imp.values) == sorted(imp.values, reverse=True)


class TestPredict:
    @pytest.mark.timeout(30)
    def test_predict_returns_series(self, model, synthetic_data):
        X, y = synthetic_data
        model.train(X, y)
        preds = model.predict(X)
        assert isinstance(preds, pd.Series)
        assert preds.name == "predicted_return"
        assert len(preds) == len(X)
        assert preds.index.equals(X.index)

    @pytest.mark.timeout(30)
    def test_predict_before_train_raises(self, model, synthetic_data):
        X, _ = synthetic_data
        with pytest.raises(ValueError, match="模型未训练"):
            model.predict(X)


class TestFeatureImportance:
    @pytest.mark.timeout(30)
    def test_get_feature_importance(self, model, synthetic_data):
        X, y = synthetic_data
        model.train(X, y)
        imp = model.get_feature_importance(top_n=3)
        assert isinstance(imp, pd.Series)
        assert len(imp) == 3

    @pytest.mark.timeout(30)
    def test_before_train_raises(self, model):
        with pytest.raises(ValueError, match="模型未训练"):
            model.get_feature_importance()


class TestSaveLoad:
    @pytest.mark.timeout(30)
    def test_save_and_load_roundtrip(self, model, synthetic_data, tmp_path):
        X, y = synthetic_data
        model.train(X, y)
        path = str(tmp_path / "catboost_model.pkl")
        model.save(path)

        loaded = CatBoostFactorModel()
        loaded.load(path)

        assert loaded.feature_names == model.feature_names
        assert loaded.params == model.params
        assert loaded.feature_importance_ is not None
        pd.testing.assert_series_equal(loaded.feature_importance_, model.feature_importance_)

        original_preds = model.predict(X)
        loaded_preds = loaded.predict(X)
        pd.testing.assert_series_equal(original_preds, loaded_preds)
