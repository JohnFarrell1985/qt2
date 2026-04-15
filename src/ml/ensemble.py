"""Ensemble 模型 — LightGBM + XGBoost + CatBoost 集成 (P2-02)

支持 rank averaging 和 stacking 两种集成方式:
- Rank Averaging: 每个模型输出排名, 取排名均值 (消除尺度差异)
- Stacking: 三模型预测值作为 meta-learner 输入
"""
from typing import Dict, Any, Optional, List

import numpy as np
import pandas as pd

from src.common.logger import get_logger

logger = get_logger(__name__)


class EnsembleFactorModel:
    """三模型集成: LGB + XGB + CatBoost

    默认使用 Rank Averaging (简单稳健);
    可选 Stacking (需额外 meta-learner 训练集)。
    """

    def __init__(
        self,
        method: str = "rank_avg",
        weights: Optional[List[float]] = None,
    ):
        """
        Args:
            method: "rank_avg" 或 "stacking"
            weights: 模型权重 [lgb_w, xgb_w, catboost_w], 仅 rank_avg 生效
        """
        self.method = method
        self.weights = weights or [1.0, 1.0, 1.0]
        self.models: Dict[str, Any] = {}
        self.meta_model = None
        self._available_models: List[str] = []

    def _init_models(self):
        from src.ml.lgb_model import LGBFactorModel
        self.models["lgb"] = LGBFactorModel()
        self._available_models.append("lgb")

        try:
            from src.ml.xgb_model import XGBFactorModel
            self.models["xgb"] = XGBFactorModel()
            self._available_models.append("xgb")
        except Exception:
            logger.warning("XGBoost 不可用, 将使用 LGB+CatBoost 双模型集成")

        try:
            from src.ml.catboost_model import CatBoostFactorModel
            self.models["catboost"] = CatBoostFactorModel()
            self._available_models.append("catboost")
        except Exception:
            logger.warning("CatBoost 不可用, 降级为单/双模型")

    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None,
        stopping_rounds: int = 50,
    ) -> Dict[str, Any]:
        if not self.models:
            self._init_models()

        all_metrics: Dict[str, Dict[str, Any]] = {}
        for name, model in self.models.items():
            try:
                metrics = model.train(X_train, y_train, X_val, y_val, stopping_rounds)
                all_metrics[name] = metrics
            except Exception as e:
                logger.error("模型 %s 训练失败: %s", name, e)

        if self.method == "stacking" and X_val is not None:
            self._train_meta(X_val, y_val)

        return {
            "ensemble_method": self.method,
            "n_models": len(all_metrics),
            "per_model": all_metrics,
        }

    def _train_meta(self, X_val: pd.DataFrame, y_val: pd.Series):
        from sklearn.linear_model import Ridge

        meta_features = self._get_meta_features(X_val)
        if meta_features.shape[1] < 2:
            logger.warning("meta features 不足, 回退到 rank_avg")
            self.method = "rank_avg"
            return

        self.meta_model = Ridge(alpha=1.0)
        self.meta_model.fit(meta_features, y_val)
        logger.info("Meta-learner 训练完成 (Ridge, %d 特征)", meta_features.shape[1])

    def _get_meta_features(self, X: pd.DataFrame) -> pd.DataFrame:
        preds = {}
        for name, model in self.models.items():
            try:
                preds[name] = model.predict(X).values
            except Exception:
                pass
        return pd.DataFrame(preds, index=X.index)

    def predict(self, X: pd.DataFrame) -> pd.Series:
        if not self.models:
            raise ValueError("模型未训练")

        if self.method == "stacking" and self.meta_model is not None:
            meta_features = self._get_meta_features(X)
            preds = self.meta_model.predict(meta_features)
            return pd.Series(preds, index=X.index, name="predicted_return")

        ranks = []
        w_used = []
        for i, (name, model) in enumerate(self.models.items()):
            try:
                pred = model.predict(X)
                rank = pred.rank(pct=True)
                ranks.append(rank)
                w_used.append(self.weights[i] if i < len(self.weights) else 1.0)
            except Exception:
                pass

        if not ranks:
            raise ValueError("所有模型预测失败")

        total_w = sum(w_used)
        combined = sum(r * w for r, w in zip(ranks, w_used)) / total_w
        combined.name = "predicted_return"
        return combined

    def get_feature_importance(self, top_n: int = 50) -> pd.DataFrame:
        result = {}
        for name, model in self.models.items():
            try:
                result[name] = model.get_feature_importance(top_n)
            except Exception:
                pass
        return pd.DataFrame(result)
