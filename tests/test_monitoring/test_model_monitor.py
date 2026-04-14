"""Tests for model drift detection."""
import numpy as np
import pandas as pd

from src.monitoring.model_monitor import ModelDriftMonitor


class TestPredictionVsActualCorr:
    def test_perfect_correlation(self):
        monitor = ModelDriftMonitor(corr_warning=0.1, psi_feature_warning=0.2, check_window=10)
        x = pd.Series(np.arange(50, dtype=float))
        result = monitor.prediction_vs_actual_corr(x, x, window=10)
        valid = result.dropna()
        assert len(valid) > 0
        assert all(abs(v - 1.0) < 1e-6 for v in valid)

    def test_random_correlation(self):
        rng = np.random.default_rng(42)
        monitor = ModelDriftMonitor(corr_warning=0.1, psi_feature_warning=0.2, check_window=10)
        pred = pd.Series(rng.standard_normal(200))
        actual = pd.Series(rng.standard_normal(200))
        result = monitor.prediction_vs_actual_corr(pred, actual, window=20)
        valid = result.dropna()
        assert abs(valid.mean()) < 0.3


class TestFeaturePSI:
    def test_identical_features(self):
        rng = np.random.default_rng(42)
        df = pd.DataFrame({"f1": rng.standard_normal(500), "f2": rng.standard_normal(500)})
        monitor = ModelDriftMonitor()
        result = monitor.feature_psi(df, df)
        assert "f1" in result
        assert result["f1"] < 0.05
        assert result["f2"] < 0.05

    def test_shifted_features(self):
        rng = np.random.default_rng(42)
        train = pd.DataFrame({"f1": rng.standard_normal(500)})
        current = pd.DataFrame({"f1": rng.standard_normal(500) + 3.0})
        monitor = ModelDriftMonitor()
        result = monitor.feature_psi(train, current)
        assert result["f1"] > 0.2

    def test_small_sample_returns_zero(self):
        train = pd.DataFrame({"f1": [1.0, 2.0]})
        current = pd.DataFrame({"f1": [3.0, 4.0]})
        monitor = ModelDriftMonitor()
        result = monitor.feature_psi(train, current)
        assert result["f1"] == 0.0


class TestDetectDrift:
    def test_output_structure(self):
        rng = np.random.default_rng(42)
        monitor = ModelDriftMonitor(corr_warning=0.1, psi_feature_warning=0.2, check_window=10)
        pred = pd.Series(rng.standard_normal(50))
        actual = pd.Series(rng.standard_normal(50))
        result = monitor.detect_drift(pred, actual)
        assert "rolling_corr_mean" in result
        assert "feature_psi" in result
        assert "drift_level" in result
        assert "action" in result

    def test_normal_drift_with_correlated_data(self):
        rng = np.random.default_rng(42)
        base = rng.standard_normal(100)
        pred = pd.Series(base)
        actual = pd.Series(base + rng.standard_normal(100) * 0.01)
        monitor = ModelDriftMonitor(corr_warning=0.1, psi_feature_warning=0.2, check_window=10)
        result = monitor.detect_drift(pred, actual)
        assert result["drift_level"] == "normal"

    def test_critical_drift_uncorrelated(self):
        rng = np.random.default_rng(42)
        pred = pd.Series(rng.standard_normal(100))
        actual = pd.Series(rng.standard_normal(100))
        monitor = ModelDriftMonitor(corr_warning=0.5, psi_feature_warning=0.2, check_window=10)
        result = monitor.detect_drift(pred, actual)
        assert result["drift_level"] == "critical"
        assert result["action"] == "retrain_model"

    def test_with_feature_psi(self):
        rng = np.random.default_rng(42)
        base = rng.standard_normal(200)
        pred = pd.Series(base)
        actual = pd.Series(base + rng.standard_normal(200) * 0.01)
        train_feat = pd.DataFrame({"f1": rng.standard_normal(500)})
        curr_feat = pd.DataFrame({"f1": rng.standard_normal(500) + 3.0})
        monitor = ModelDriftMonitor(corr_warning=0.1, psi_feature_warning=0.2, check_window=10)
        result = monitor.detect_drift(pred, actual, train_feat, curr_feat)
        assert "f1" in result["feature_psi"]
        assert result["feature_psi"]["f1"] > 0.2
