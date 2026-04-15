"""CatBoost 因子模型

真正的 CatBoost 实现, 与 LGBFactorModel 接口对齐。
特性: 原生类别特征处理, Ordered Boosting 防止标签泄露。
API 参考: https://catboost.ai/en/docs/
"""
from pathlib import Path
from typing import Dict, Any, Optional, List

import numpy as np
import pandas as pd
import joblib

from src.common.logger import get_logger

logger = get_logger(__name__)


class CatBoostFactorModel:
    """CatBoost 因子选股模型

    与 LGBFactorModel 接口一致。CatBoost 的 Ordered Boosting
    天然降低过拟合风险, 适合金融时序数据。
    """

    DEFAULT_PARAMS: Dict[str, Any] = {
        "iterations": 1000,
        "learning_rate": 0.05,
        "depth": 6,
        "l2_leaf_reg": 3.0,
        "subsample": 0.8,
        "random_seed": 42,
        "verbose": 0,
        "loss_function": "RMSE",
        "eval_metric": "RMSE",
        "boosting_type": "Ordered",
    }

    def __init__(self, params: Optional[Dict] = None):
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}
        self.model = None
        self.feature_names: List[str] = []
        self.feature_importance_: Optional[pd.Series] = None
        self.best_iteration_: int = 0

    def _get_regressor(self):
        try:
            from catboost import CatBoostRegressor
        except ImportError:
            raise RuntimeError(
                "catboost 未安装。请运行: uv pip install catboost>=1.2"
            )
        return CatBoostRegressor(**self.params)

    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None,
        stopping_rounds: int = 50,
    ) -> Dict[str, Any]:
        self.feature_names = list(X_train.columns)
        self.model = self._get_regressor()

        fit_kwargs: Dict[str, Any] = {}
        if X_val is not None and y_val is not None:
            fit_kwargs["eval_set"] = (X_val, y_val)
            if stopping_rounds > 0:
                fit_kwargs["early_stopping_rounds"] = stopping_rounds

        self.model.fit(X_train, y_train, **fit_kwargs)

        self.best_iteration_ = getattr(
            self.model, "best_iteration_", self.params.get("iterations", 0)
        )

        self.feature_importance_ = pd.Series(
            self.model.get_feature_importance(),
            index=self.feature_names,
        ).sort_values(ascending=False)

        metrics: Dict[str, Any] = {
            "model_type": "catboost",
            "n_features": len(self.feature_names),
            "n_samples": len(X_train),
            "best_iteration": self.best_iteration_,
        }
        if X_val is not None:
            pred_val = np.asarray(self.model.predict(X_val))
            mse = float(np.mean((pred_val - y_val.values) ** 2))
            ic = float(
                pd.Series(pred_val).corr(y_val.reset_index(drop=True), method="spearman")
            )
            metrics["val_mse"] = round(mse, 6)
            metrics["val_ic"] = round(ic, 4)

        logger.info("CatBoost 训练完成: %s", metrics)
        return metrics

    def predict(self, X: pd.DataFrame) -> pd.Series:
        if self.model is None:
            raise ValueError("模型未训练")
        preds = self.model.predict(X)
        return pd.Series(preds, index=X.index, name="predicted_return")

    def get_feature_importance(self, top_n: int = 50) -> pd.Series:
        if self.feature_importance_ is None:
            raise ValueError("模型未训练")
        return self.feature_importance_.head(top_n)

    def rolling_train(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        window: int = 252,
        step: int = 21,
    ) -> List[Dict[str, Any]]:
        dates = X.index.get_level_values("trade_date")
        unique_dates = sorted(dates.unique())
        results = []

        for i in range(window, len(unique_dates), step):
            val_end_idx = min(i + step, len(unique_dates))
            train_dates = unique_dates[max(0, i - window): i]
            val_dates = unique_dates[i: val_end_idx]
            train_mask = dates.isin(train_dates)
            val_mask = dates.isin(val_dates)
            if train_mask.sum() < 100 or val_mask.sum() < 10:
                continue
            m = self.train(X[train_mask], y[train_mask], X[val_mask], y[val_mask])
            m["train_period"] = f"{train_dates[0]}~{train_dates[-1]}"
            m["val_period"] = f"{val_dates[0]}~{val_dates[-1]}"
            results.append(m)

        logger.info("CatBoost 滚动训练完成: %d 轮", len(results))
        return results

    def save(self, path: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "model": self.model,
            "params": self.params,
            "feature_names": self.feature_names,
            "feature_importance": self.feature_importance_,
        }, str(p))
        logger.info("CatBoost 模型已保存: %s", path)

    def load(self, path: str) -> None:
        data = joblib.load(path)
        self.model = data["model"]
        self.params = data["params"]
        self.feature_names = data["feature_names"]
        self.feature_importance_ = data.get("feature_importance")
        logger.info("CatBoost 模型已加载: %s", path)
