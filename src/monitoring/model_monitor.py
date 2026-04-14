"""模型漂移检测

KPIs:
  - 预测值 vs 实际收益滚动相关性
  - 特征 PSI: 检测输入特征分布偏移
  - 综合漂移等级与响应建议

References:
  - Advances in Financial Machine Learning
  - stockalpha.ai: Concept Drift Alarms for Quant Signals
"""
import pandas as pd

from src.common.config import settings
from src.common.logger import get_logger
from src.monitoring.factor_monitor import calc_psi

logger = get_logger(__name__)


class ModelDriftMonitor:
    """Monitors model prediction quality and feature distribution stability."""

    def __init__(
        self,
        corr_warning: float = settings.model_monitor.corr_warning,
        psi_feature_warning: float = settings.model_monitor.psi_feature_warning,
        check_window: int = settings.model_monitor.check_window,
    ):
        self.corr_warning = corr_warning
        self.psi_feature_warning = psi_feature_warning
        self.check_window = check_window

    def prediction_vs_actual_corr(
        self,
        predictions: pd.Series,
        actuals: pd.Series,
        window: int = 20,
    ) -> pd.Series:
        """Rolling Pearson correlation between predictions and actuals."""
        pred = predictions.reset_index(drop=True)
        act = actuals.reset_index(drop=True)
        return pred.rolling(window=window, min_periods=max(window // 2, 2)).corr(act)

    def feature_psi(
        self,
        train_features: pd.DataFrame,
        current_features: pd.DataFrame,
    ) -> dict[str, float]:
        """Per-feature PSI between training and current data."""
        common_cols = train_features.columns.intersection(current_features.columns)
        result: dict[str, float] = {}
        for col in common_cols:
            train_vals = train_features[col].dropna().values
            curr_vals = current_features[col].dropna().values
            if len(train_vals) < 10 or len(curr_vals) < 10:
                result[col] = 0.0
                continue
            result[col] = calc_psi(train_vals, curr_vals)
        return result

    def detect_drift(
        self,
        predictions: pd.Series,
        actuals: pd.Series,
        train_features: pd.DataFrame | None = None,
        current_features: pd.DataFrame | None = None,
    ) -> dict:
        """Comprehensive drift detection.

        Returns
        -------
        dict with keys: rolling_corr_mean, feature_psi, drift_level, action
        """
        rolling_corr = self.prediction_vs_actual_corr(
            predictions, actuals, window=self.check_window
        )
        valid_corr = rolling_corr.dropna()
        corr_mean = float(valid_corr.mean()) if len(valid_corr) > 0 else 0.0

        feat_psi: dict[str, float] = {}
        if train_features is not None and current_features is not None:
            feat_psi = self.feature_psi(train_features, current_features)

        max_feat_psi = max(feat_psi.values()) if feat_psi else 0.0

        drift_level = "normal"
        action = "continue"

        if corr_mean < self.corr_warning or max_feat_psi > self.psi_feature_warning * 2:
            drift_level = "critical"
            action = "retrain_model"
            logger.warning(
                "模型严重漂移 corr=%.4f, max_feature_psi=%.4f, 建议立即重训",
                corr_mean, max_feat_psi,
            )
        elif max_feat_psi > self.psi_feature_warning:
            drift_level = "warning"
            action = "review_features"
            logger.warning(
                "特征分布偏移 max_feature_psi=%.4f", max_feat_psi,
            )
        else:
            logger.info("模型状态正常 corr=%.4f, max_psi=%.4f", corr_mean, max_feat_psi)

        return {
            "rolling_corr_mean": corr_mean,
            "feature_psi": feat_psi,
            "drift_level": drift_level,
            "action": action,
        }
