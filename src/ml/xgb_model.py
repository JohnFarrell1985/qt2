"""XGBoost 因子模型

真正的 XGBoost 实现, 与 LGBFactorModel 接口对齐。
API 参考: https://xgboost.readthedocs.io/en/stable/python/python_api.html
"""
from pathlib import Path
from typing import Dict, Any, Optional, List

import numpy as np
import pandas as pd
import joblib

from src.common.logger import get_logger

logger = get_logger(__name__)


class XGBFactorModel:
    """XGBoost 因子选股模型

    与 LGBFactorModel 接口一致:
    - train(X_train, y_train, X_val, y_val) → metrics
    - predict(X) → Series
    - get_feature_importance(top_n) → Series
    - rolling_train(X, y, window, step) → list[metrics]
    - save(path) / load(path)
    """

    DEFAULT_PARAMS: Dict[str, Any] = {
        "objective": "reg:squarederror",
        "eval_metric": "rmse",
        "max_depth": 6,
        "learning_rate": 0.05,
        "n_estimators": 1000,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "tree_method": "hist",
        "verbosity": 0,
        "n_jobs": -1,
    }

    def __init__(self, params: Optional[Dict] = None):
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}
        self.model = None
        self.feature_names: List[str] = []
        self.feature_importance_: Optional[pd.Series] = None
        self.best_iteration_: int = 0

    def _get_regressor(self):
        try:
            from xgboost import XGBRegressor
        except ImportError:
            raise RuntimeError(
                "xgboost 未安装。请运行: uv pip install xgboost>=2.0"
            )
        return XGBRegressor(**self.params)

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
            fit_kwargs["eval_set"] = [(X_val, y_val)]
            if stopping_rounds > 0:
                from xgboost.callback import EarlyStopping
                fit_kwargs["callbacks"] = [EarlyStopping(rounds=stopping_rounds)]

        self.model.fit(X_train, y_train, **fit_kwargs)

        self.best_iteration_ = getattr(
            self.model, "best_iteration", self.params.get("n_estimators", 0)
        )

        self.feature_importance_ = pd.Series(
            self.model.feature_importances_,
            index=self.feature_names,
        ).sort_values(ascending=False)

        metrics: Dict[str, Any] = {
            "model_type": "xgboost",
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

        logger.info("XGBoost 训练完成: %s", metrics)
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

        logger.info("XGBoost 滚动训练完成: %d 轮", len(results))
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
        logger.info("XGBoost 模型已保存: %s", path)

    def load(self, path: str) -> None:
        data = joblib.load(path)
        self.model = data["model"]
        self.params = data["params"]
        self.feature_names = data["feature_names"]
        self.feature_importance_ = data.get("feature_importance")
        logger.info("XGBoost 模型已加载: %s", path)
