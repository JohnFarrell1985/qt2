"""LightGBM因子模型

训练、预测、因子重要性分析。
API 参考: https://lightgbm.readthedocs.io/en/stable/pythonapi/lightgbm.LGBMRegressor.html
"""
from pathlib import Path
from typing import Dict, Any, Optional, List

import numpy as np
import pandas as pd
import lightgbm as lgb
import joblib

from src.common.logger import get_logger

logger = get_logger(__name__)

# sklearn-compatible 参数直接传给 LGBMRegressor 构造函数
# 其余 LightGBM 原生参数通过 **kwargs 传递（官方文档有警告但实际可用）
_SKLEARN_PARAMS = {"n_estimators", "boosting_type", "num_leaves", "learning_rate",
                   "subsample", "colsample_bytree", "reg_alpha", "reg_lambda",
                   "min_child_samples", "importance_type", "n_jobs", "random_state"}


class LGBFactorModel:
    """LightGBM 因子选股模型"""

    DEFAULT_PARAMS = {
        "objective": "regression",
        "metric": "mse",
        "boosting_type": "gbdt",
        "num_leaves": 63,
        "learning_rate": 0.05,
        "n_estimators": 1000,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "importance_type": "gain",
        "verbose": -1,
        "n_jobs": -1,
    }

    def __init__(self, params: Optional[Dict] = None):
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}
        self.model: Optional[lgb.LGBMRegressor] = None
        self.feature_names: List[str] = []
        self.feature_importance_: Optional[pd.Series] = None
        self.best_iteration_: int = 0

    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: Optional[pd.DataFrame] = None,
        y_val: Optional[pd.Series] = None,
        stopping_rounds: int = 50,
    ) -> Dict[str, Any]:
        """训练模型

        LightGBM >= 4.0: early_stopping 必须通过 callback 传递，
        不能直接传给 fit()。
        """
        self.feature_names = list(X_train.columns)

        callbacks = [lgb.log_evaluation(period=100)]
        if stopping_rounds > 0 and X_val is not None:
            callbacks.append(lgb.early_stopping(stopping_rounds=stopping_rounds))

        self.model = lgb.LGBMRegressor(**self.params)

        eval_set = [(X_val, y_val)] if X_val is not None else None

        self.model.fit(
            X_train, y_train,
            eval_set=eval_set,
            callbacks=callbacks,
        )

        self.best_iteration_ = getattr(self.model, "best_iteration_", self.params.get("n_estimators", 0))

        self.feature_importance_ = pd.Series(
            self.model.feature_importances_,
            index=self.feature_names,
        ).sort_values(ascending=False)

        metrics = {
            "n_features": len(self.feature_names),
            "n_samples": len(X_train),
            "best_iteration": self.best_iteration_,
        }
        if X_val is not None:
            pred_val = np.asarray(self.model.predict(X_val))
            mse = float(np.mean((pred_val - y_val.values) ** 2))
            ic = float(pd.Series(pred_val).corr(y_val.reset_index(drop=True), method="spearman"))
            metrics["val_mse"] = round(mse, 6)
            metrics["val_ic"] = round(ic, 4)

        logger.info(f"模型训练完成: {metrics}")
        return metrics

    def predict(self, X: pd.DataFrame) -> pd.Series:
        """预测"""
        if self.model is None:
            raise ValueError("模型未训练")
        preds = self.model.predict(X)
        return pd.Series(preds, index=X.index, name="predicted_return")

    def get_feature_importance(self, top_n: int = 50) -> pd.Series:
        """获取因子重要性排名"""
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
        """滚动训练 (每step天重训，窗口window天)"""
        dates = X.index.get_level_values("trade_date")
        unique_dates = sorted(dates.unique())
        results = []

        for i in range(window, len(unique_dates), step):
            train_end_idx = i
            val_end_idx = min(i + step, len(unique_dates))

            train_dates = unique_dates[max(0, i - window):i]
            val_dates = unique_dates[i:val_end_idx]

            train_mask = dates.isin(train_dates)
            val_mask = dates.isin(val_dates)

            if train_mask.sum() < 100 or val_mask.sum() < 10:
                continue

            metrics = self.train(
                X[train_mask], y[train_mask],
                X[val_mask], y[val_mask],
            )
            metrics["train_period"] = f"{train_dates[0]}~{train_dates[-1]}"
            metrics["val_period"] = f"{val_dates[0]}~{val_dates[-1]}"
            results.append(metrics)

        logger.info(f"滚动训练完成: {len(results)} 轮")
        return results

    def save(self, path: str) -> None:
        """保存模型"""
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({
            "model": self.model,
            "params": self.params,
            "feature_names": self.feature_names,
            "feature_importance": self.feature_importance_,
        }, str(p))
        logger.info(f"模型已保存: {path}")

    def load(self, path: str) -> None:
        """加载模型"""
        data = joblib.load(path)
        self.model = data["model"]
        self.params = data["params"]
        self.feature_names = data["feature_names"]
        self.feature_importance_ = data.get("feature_importance")
        logger.info(f"模型已加载: {path}")
