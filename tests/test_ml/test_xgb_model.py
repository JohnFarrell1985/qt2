"""Tests for src/ml/xgb_model.py - XGBFactorModel"""
import numpy as np
import pandas as pd
import pytest

xgb = pytest.importorskip("xgboost")

from src.ml.xgb_model import XGBFactorModel


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
    return {"n_estimators": 20, "max_depth": 3, "verbosity": 0, "n_jobs": 1}


@pytest.fixture
def model(small_params):
    return XGBFactorModel(params=small_params)


class TestInit:
    @pytest.mark.timeout(30)
    def test_default_params(self):
        m = XGBFactorModel()
        assert m.params["objective"] == "reg:squarederror"
        assert m.model is None
        assert m.feature_names == []
        assert m.feature_importance_ is None

    @pytest.mark.timeout(30)
    def test_custom_params_override(self):
        m = XGBFactorModel(params={"max_depth": 3, "learning_rate": 0.1})
        assert m.params["max_depth"] == 3
        assert m.params["learning_rate"] == 0.1
        assert m.params["objective"] == "reg:squarederror"


class TestTrain:
    @pytest.mark.timeout(30)
    def test_train_without_validation(self, model, synthetic_data):
        X, y = synthetic_data
        metrics = model.train(X, y)
        assert metrics["model_type"] == "xgboost"
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
        path = str(tmp_path / "xgb_model.pkl")
        model.save(path)

        loaded = XGBFactorModel()
        loaded.load(path)

        assert loaded.feature_names == model.feature_names
        assert loaded.params == model.params
        assert loaded.feature_importance_ is not None
        pd.testing.assert_series_equal(loaded.feature_importance_, model.feature_importance_)

        original_preds = model.predict(X)
        loaded_preds = loaded.predict(X)
        pd.testing.assert_series_equal(original_preds, loaded_preds)

    @pytest.mark.timeout(30)
    def test_save_creates_parent_dirs(self, model, synthetic_data, tmp_path):
        X, y = synthetic_data
        model.train(X, y)
        path = str(tmp_path / "a" / "b" / "model.pkl")
        model.save(path)
        from pathlib import Path
        assert Path(path).exists()


class TestRollingTrain:
    @pytest.mark.timeout(30)
    def test_rolling_train_basic(self, small_params):
        rng = np.random.RandomState(0)
        n_dates = 40
        n_stocks = 20
        dates = pd.bdate_range("2024-01-01", periods=n_dates)
        codes = [f"{i:06d}" for i in range(1, n_stocks + 1)]
        index = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])
        X = pd.DataFrame({f"f{i}": rng.randn(len(index)) for i in range(3)}, index=index)
        y = pd.Series(rng.randn(len(index)) * 0.01, index=index)

        m = XGBFactorModel(params=small_params)
        results = m.rolling_train(X, y, window=15, step=5)
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert "train_period" in r
            assert "val_period" in r
            assert r["model_type"] == "xgboost"
