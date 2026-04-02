"""Tests for src/ml/lgb_model.py - LGBFactorModel"""
import numpy as np
import pandas as pd
import pytest
import lightgbm as lgb


@pytest.fixture
def synthetic_data():
    """Small synthetic dataset: 200 rows, 5 features, MultiIndex(trade_date, code)."""
    rng = np.random.RandomState(42)
    n = 200
    dates = pd.bdate_range("2024-01-01", periods=10)
    codes = [f"{i:06d}" for i in range(1, 21)]
    index = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])

    features = {f"f{i}": rng.randn(n) for i in range(5)}
    X = pd.DataFrame(features, index=index)
    y = pd.Series(rng.randn(n) * 0.01, index=index, name="forward_return")
    return X, y


@pytest.fixture
def small_params():
    return {"n_estimators": 20, "num_leaves": 8, "verbose": -1, "n_jobs": 1}


@pytest.fixture
def model(small_params):
    from src.ml.lgb_model import LGBFactorModel
    return LGBFactorModel(params=small_params)


class TestInit:
    def test_default_params(self):
        from src.ml.lgb_model import LGBFactorModel
        m = LGBFactorModel()
        assert m.params["objective"] == "regression"
        assert m.params["metric"] == "mse"
        assert m.params["num_leaves"] == 63
        assert m.model is None
        assert m.feature_names == []
        assert m.feature_importance_ is None
        assert m.best_iteration_ == 0

    def test_custom_params_override(self):
        from src.ml.lgb_model import LGBFactorModel
        m = LGBFactorModel(params={"num_leaves": 31, "learning_rate": 0.1})
        assert m.params["num_leaves"] == 31
        assert m.params["learning_rate"] == 0.1
        assert m.params["objective"] == "regression"

    def test_none_params_uses_defaults(self):
        from src.ml.lgb_model import LGBFactorModel
        m = LGBFactorModel(params=None)
        assert m.params == LGBFactorModel.DEFAULT_PARAMS


class TestTrain:
    def test_train_without_validation(self, model, synthetic_data):
        X, y = synthetic_data
        metrics = model.train(X, y)
        assert "n_features" in metrics
        assert metrics["n_features"] == 5
        assert metrics["n_samples"] == 200
        assert "best_iteration" in metrics
        assert "val_mse" not in metrics
        assert "val_ic" not in metrics
        assert model.model is not None
        assert model.feature_names == list(X.columns)
        assert model.feature_importance_ is not None

    def test_train_with_validation(self, model, synthetic_data):
        X, y = synthetic_data
        split = 160
        X_train, X_val = X.iloc[:split], X.iloc[split:]
        y_train, y_val = y.iloc[:split], y.iloc[split:]

        metrics = model.train(X_train, y_train, X_val, y_val, stopping_rounds=5)
        assert "val_mse" in metrics
        assert "val_ic" in metrics
        assert isinstance(metrics["val_mse"], float)
        assert isinstance(metrics["val_ic"], float)
        assert metrics["val_mse"] >= 0

    def test_train_with_stopping_rounds_zero(self, synthetic_data):
        from src.ml.lgb_model import LGBFactorModel
        m = LGBFactorModel(params={"n_estimators": 20, "verbose": -1, "n_jobs": 1})
        X, y = synthetic_data
        split = 160
        metrics = m.train(X.iloc[:split], y.iloc[:split],
                          X.iloc[split:], y.iloc[split:], stopping_rounds=0)
        assert "n_features" in metrics

    def test_feature_importance_sorted_descending(self, model, synthetic_data):
        X, y = synthetic_data
        model.train(X, y)
        imp = model.feature_importance_
        assert list(imp.values) == sorted(imp.values, reverse=True)

    def test_model_is_lgbm_regressor(self, model, synthetic_data):
        X, y = synthetic_data
        model.train(X, y)
        assert isinstance(model.model, lgb.LGBMRegressor)


class TestPredict:
    def test_predict_returns_series(self, model, synthetic_data):
        X, y = synthetic_data
        model.train(X, y)
        preds = model.predict(X)
        assert isinstance(preds, pd.Series)
        assert preds.name == "predicted_return"
        assert len(preds) == len(X)
        assert preds.index.equals(X.index)

    def test_predict_before_train_raises(self, model, synthetic_data):
        X, _ = synthetic_data
        with pytest.raises(ValueError, match="模型未训练"):
            model.predict(X)


class TestFeatureImportance:
    def test_get_feature_importance(self, model, synthetic_data):
        X, y = synthetic_data
        model.train(X, y)
        imp = model.get_feature_importance(top_n=3)
        assert isinstance(imp, pd.Series)
        assert len(imp) == 3

    def test_get_all_features(self, model, synthetic_data):
        X, y = synthetic_data
        model.train(X, y)
        imp = model.get_feature_importance(top_n=50)
        assert len(imp) == 5

    def test_feature_importance_before_train_raises(self, model):
        with pytest.raises(ValueError, match="模型未训练"):
            model.get_feature_importance()


class TestSaveLoad:
    def test_save_and_load(self, model, synthetic_data, tmp_path):
        X, y = synthetic_data
        model.train(X, y)
        path = str(tmp_path / "sub" / "model.pkl")
        model.save(path)

        from src.ml.lgb_model import LGBFactorModel
        loaded = LGBFactorModel()
        loaded.load(path)

        assert loaded.feature_names == model.feature_names
        assert loaded.params == model.params
        assert loaded.feature_importance_ is not None
        pd.testing.assert_series_equal(loaded.feature_importance_, model.feature_importance_)

        original_preds = model.predict(X)
        loaded_preds = loaded.predict(X)
        pd.testing.assert_series_equal(original_preds, loaded_preds)

    def test_save_creates_parent_dirs(self, model, synthetic_data, tmp_path):
        X, y = synthetic_data
        model.train(X, y)
        path = str(tmp_path / "a" / "b" / "c" / "model.pkl")
        model.save(path)
        from pathlib import Path
        assert Path(path).exists()


class TestRollingTrain:
    def test_rolling_train_basic(self, small_params):
        from src.ml.lgb_model import LGBFactorModel
        rng = np.random.RandomState(0)
        n_dates = 40
        n_stocks = 20
        dates = pd.bdate_range("2024-01-01", periods=n_dates)
        codes = [f"{i:06d}" for i in range(1, n_stocks + 1)]
        index = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])
        X = pd.DataFrame({f"f{i}": rng.randn(len(index)) for i in range(3)}, index=index)
        y = pd.Series(rng.randn(len(index)) * 0.01, index=index)

        m = LGBFactorModel(params=small_params)
        results = m.rolling_train(X, y, window=15, step=5)
        assert isinstance(results, list)
        assert len(results) > 0
        for r in results:
            assert "train_period" in r
            assert "val_period" in r
            assert "n_features" in r

    def test_rolling_train_skips_small_windows(self, small_params):
        from src.ml.lgb_model import LGBFactorModel
        rng = np.random.RandomState(1)
        dates = pd.bdate_range("2024-01-01", periods=5)
        codes = [f"{i:06d}" for i in range(1, 4)]
        index = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])
        X = pd.DataFrame({"f0": rng.randn(len(index))}, index=index)
        y = pd.Series(rng.randn(len(index)), index=index)

        m = LGBFactorModel(params=small_params)
        results = m.rolling_train(X, y, window=3, step=1)
        assert isinstance(results, list)
