"""E2E: 模型漂移检测 — 用真实行情数据模拟预测值, 验证漂移检测逻辑"""
import numpy as np
import pandas as pd
import pytest

from src.monitoring.model_monitor import ModelDriftMonitor


class TestPredictionVsActualWithRealData:

    @pytest.fixture
    def pred_actual_pair(self, real_stock_daily_df):
        """用真实收益率构造伪预测: pred = 滞后 ret + noise"""
        df = real_stock_daily_df.sort_values("trade_date").copy()
        df["ret"] = df["close"].pct_change()
        df = df.dropna().reset_index(drop=True)

        actuals = df["ret"]
        rng = np.random.default_rng(42)
        noise = pd.Series(rng.normal(0, actuals.std() * 0.5, len(actuals)), index=actuals.index)
        predictions = actuals.shift(1).fillna(0) + noise
        return predictions, actuals

    def test_rolling_corr_shape(self, pred_actual_pair):
        predictions, actuals = pred_actual_pair
        monitor = ModelDriftMonitor(check_window=20)
        corr = monitor.prediction_vs_actual_corr(predictions, actuals, window=20)
        assert len(corr) == len(predictions)

    def test_rolling_corr_bounded(self, pred_actual_pair):
        predictions, actuals = pred_actual_pair
        monitor = ModelDriftMonitor()
        corr = monitor.prediction_vs_actual_corr(predictions, actuals, window=20)
        valid = corr.dropna()
        assert (valid.abs() <= 1.0 + 1e-9).all()


class TestFeaturePSIWithRealData:

    @pytest.fixture
    def feature_dfs(self, real_stock_daily_df):
        """将真实数据分成两半, 模拟 train / current 特征集"""
        df = real_stock_daily_df.sort_values("trade_date").copy()
        df["ret_5"] = df["close"].pct_change(5)
        df["ret_10"] = df["close"].pct_change(10)
        df["vol_ratio"] = df["volume"] / df["volume"].rolling(20).mean()
        df = df.dropna().reset_index(drop=True)
        mid = len(df) // 2
        return (
            df[["ret_5", "ret_10", "vol_ratio"]].iloc[:mid],
            df[["ret_5", "ret_10", "vol_ratio"]].iloc[mid:],
        )

    def test_feature_psi_all_columns(self, feature_dfs):
        train_feat, curr_feat = feature_dfs
        monitor = ModelDriftMonitor()
        psi_map = monitor.feature_psi(train_feat, curr_feat)

        assert "ret_5" in psi_map
        assert "ret_10" in psi_map
        assert "vol_ratio" in psi_map
        for col, val in psi_map.items():
            assert val >= 0.0, f"PSI for {col} should be >= 0"

    def test_same_data_psi_near_zero(self, feature_dfs):
        train_feat, _ = feature_dfs
        monitor = ModelDriftMonitor()
        psi_map = monitor.feature_psi(train_feat, train_feat)
        for col, val in psi_map.items():
            assert val < 0.01, f"Same data PSI for {col} should be ~0, got {val:.4f}"


class TestDetectDriftE2E:

    @pytest.fixture
    def drift_inputs(self, real_stock_daily_df):
        df = real_stock_daily_df.sort_values("trade_date").copy()
        df["ret"] = df["close"].pct_change()
        df["ret_5"] = df["close"].pct_change(5)
        df["ret_10"] = df["close"].pct_change(10)
        df = df.dropna().reset_index(drop=True)
        mid = len(df) // 2

        actuals = df["ret"]
        rng = np.random.default_rng(42)
        predictions = actuals + pd.Series(
            rng.normal(0, actuals.std() * 0.3, len(actuals)), index=actuals.index,
        )

        train_feat = df[["ret_5", "ret_10"]].iloc[:mid]
        curr_feat = df[["ret_5", "ret_10"]].iloc[mid:]
        return predictions, actuals, train_feat, curr_feat

    def test_detect_drift_complete_report(self, drift_inputs):
        predictions, actuals, train_feat, curr_feat = drift_inputs
        monitor = ModelDriftMonitor()
        result = monitor.detect_drift(
            predictions, actuals, train_feat, curr_feat,
        )

        assert "rolling_corr_mean" in result
        assert "feature_psi" in result
        assert "drift_level" in result
        assert "action" in result
        assert result["drift_level"] in ("normal", "warning", "critical")
        assert result["action"] in ("continue", "review_features", "retrain_model")

    def test_good_predictions_show_low_drift(self, real_stock_daily_df):
        """高质量预测 (加小噪声) 不应报 critical"""
        df = real_stock_daily_df.sort_values("trade_date").copy()
        df["ret"] = df["close"].pct_change()
        df = df.dropna().reset_index(drop=True)

        actuals = df["ret"]
        rng = np.random.default_rng(42)
        predictions = actuals + pd.Series(
            rng.normal(0, actuals.std() * 0.1, len(actuals)), index=actuals.index,
        )

        monitor = ModelDriftMonitor(corr_warning=0.1)
        result = monitor.detect_drift(predictions, actuals)
        assert result["drift_level"] != "critical", (
            f"Good predictions should not be critical, corr={result['rolling_corr_mean']:.4f}"
        )
