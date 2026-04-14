"""Rolling Walk-Forward Retrain Engine

滚动前推重训练引擎, 支持 24+6+6 (或自定义) 月滚动窗口:
  - 训练窗口: [T-30m, T-6m]
  - 验证窗口: [T-6m, T]
  - 测试窗口: [T, T+6m]
窗口按 step_months 步长前进, 各测试期不重叠。

参考: Walk-Forward Analysis / Anchored vs Rolling 方法论。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date
from dateutil.relativedelta import relativedelta

import numpy as np
import pandas as pd

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import MLModelLog
from src.ml.dataset import FactorDataset
from src.ml.lgb_model import LGBFactorModel
from src.ml.model_evaluation import evaluate_predictions

logger = get_logger(__name__)


@dataclass
class WalkForwardWindow:
    """Single walk-forward window definition."""

    train_start: date
    train_end: date
    val_start: date
    val_end: date
    test_start: date
    test_end: date
    window_id: int


class RollingWalkForward:
    """Rolling Walk-Forward Retrain Engine.

    Implements configurable rolling windows (default 24+6+6 months).
    Each window: train on [train_start, train_end], validate on [val_start, val_end],
    test on [test_start, test_end].
    Windows advance by ``step_months`` months.
    """

    def __init__(
        self,
        train_months: int = 24,
        val_months: int = 6,
        test_months: int = 6,
        step_months: int = 6,
        start_date: date | None = None,
        end_date: date | None = None,
    ):
        if train_months <= 0 or val_months <= 0 or test_months <= 0 or step_months <= 0:
            raise ValueError("All month parameters must be positive")
        self.train_months = train_months
        self.val_months = val_months
        self.test_months = test_months
        self.step_months = step_months
        self.start_date = start_date or date(2018, 1, 1)
        self.end_date = end_date or date.today()
        self.windows: list[WalkForwardWindow] = []
        self.results: list[dict] = []

    def generate_windows(self) -> list[WalkForwardWindow]:
        """Generate all walk-forward windows from start to end date.

        The first window's train_start is anchored at ``self.start_date``.
        Subsequent windows shift forward by ``step_months``.
        Windows whose test_end exceeds ``self.end_date`` are discarded.
        """
        windows: list[WalkForwardWindow] = []
        cursor = self.start_date
        window_id = 0

        while True:
            train_start = cursor
            train_end = train_start + relativedelta(months=self.train_months) - relativedelta(days=1)
            val_start = train_end + relativedelta(days=1)
            val_end = val_start + relativedelta(months=self.val_months) - relativedelta(days=1)
            test_start = val_end + relativedelta(days=1)
            test_end = test_start + relativedelta(months=self.test_months) - relativedelta(days=1)

            if test_end > self.end_date:
                break

            windows.append(
                WalkForwardWindow(
                    train_start=train_start,
                    train_end=train_end,
                    val_start=val_start,
                    val_end=val_end,
                    test_start=test_start,
                    test_end=test_end,
                    window_id=window_id,
                )
            )
            window_id += 1
            cursor = cursor + relativedelta(months=self.step_months)

        self.windows = windows
        logger.info(f"生成 {len(windows)} 个 walk-forward 窗口")
        return windows

    def run(
        self,
        factor_names: list[str],
        stock_pool: list[str],
        label_period: int = 5,
    ) -> list[dict]:
        """Execute rolling walk-forward across all windows.

        For each window:
        1. Build FactorDataset for train/val/test periods
        2. Train LGBFactorModel
        3. Evaluate on test set
        4. Record metrics (IC, ICIR, Sharpe, etc.)
        5. Log to DB

        Returns:
            list of per-window metrics dicts.
        """
        if not self.windows:
            self.generate_windows()

        if not self.windows:
            logger.warning("无可用窗口, 请检查日期范围")
            return []

        logger.info(
            f"开始 Walk-Forward 回测: {len(self.windows)} 窗口, "
            f"{len(factor_names)} 因子, {len(stock_pool)} 只股票"
        )

        self.results = []
        for window in self.windows:
            t0 = time.time()
            result = self._run_single_window(window, factor_names, stock_pool, label_period)
            elapsed = time.time() - t0
            result["elapsed_sec"] = round(elapsed, 2)
            self.results.append(result)

            logger.info(
                f"窗口 #{window.window_id} 完成: "
                f"IC={result.get('ic_mean', 'N/A')}, "
                f"ICIR={result.get('icir', 'N/A')}, "
                f"耗时 {elapsed:.1f}s"
            )

        self._log_summary()
        return self.results

    def _run_single_window(
        self,
        window: WalkForwardWindow,
        factor_names: list[str],
        stock_pool: list[str],
        label_period: int,
    ) -> dict:
        """Execute a single walk-forward window."""
        result: dict = {
            "window_id": window.window_id,
            "train_period": f"{window.train_start}~{window.train_end}",
            "val_period": f"{window.val_start}~{window.val_end}",
            "test_period": f"{window.test_start}~{window.test_end}",
        }

        ds = FactorDataset()
        X_train, y_train = ds.build(
            factor_names=factor_names,
            stock_pool=stock_pool,
            start_date=window.train_start,
            end_date=window.train_end,
            label_period=label_period,
        )
        if X_train.empty:
            logger.warning(f"窗口 #{window.window_id} 训练数据为空, 跳过")
            result["status"] = "skip_no_train_data"
            return result

        ds_val = FactorDataset()
        X_val, y_val = ds_val.build(
            factor_names=factor_names,
            stock_pool=stock_pool,
            start_date=window.val_start,
            end_date=window.val_end,
            label_period=label_period,
        )

        ds_test = FactorDataset()
        X_test, y_test = ds_test.build(
            factor_names=factor_names,
            stock_pool=stock_pool,
            start_date=window.test_start,
            end_date=window.test_end,
            label_period=label_period,
        )

        model = LGBFactorModel()
        train_metrics = model.train(
            X_train,
            y_train,
            X_val if not X_val.empty else None,
            y_val if not y_val.empty else None,
            stopping_rounds=50,
        )
        result["train_metrics"] = train_metrics

        if X_test.empty:
            logger.warning(f"窗口 #{window.window_id} 测试数据为空")
            result["status"] = "skip_no_test_data"
            return result

        pred_test = model.predict(X_test)
        eval_result = evaluate_predictions(pred_test, y_test, n_groups=5)
        result.update(eval_result)
        result["status"] = "ok"

        importance = model.get_feature_importance(len(factor_names))
        result["feature_importance"] = importance.to_dict()

        self._log_window_to_db(window, result)
        return result

    def _log_window_to_db(self, window: WalkForwardWindow, result: dict) -> None:
        """Record per-window metrics to database."""
        try:
            with get_session() as session:
                log = MLModelLog(
                    model_name=f"wf_window_{window.window_id}",
                    train_start=window.train_start,
                    train_end=window.train_end,
                    n_features=result.get("train_metrics", {}).get("n_features"),
                    n_samples=result.get("train_metrics", {}).get("n_samples"),
                    ic_mean=result.get("ic_mean"),
                    icir=result.get("icir"),
                    mse=result.get("train_metrics", {}).get("val_mse"),
                    params_json=json.dumps({
                        "test_period": result.get("test_period"),
                        "status": result.get("status"),
                    }),
                )
                session.add(log)
        except Exception as e:
            logger.warning(f"窗口 #{window.window_id} DB 日志写入失败: {e}")

    def _log_summary(self) -> None:
        """Log walk-forward summary statistics."""
        ok_results = [r for r in self.results if r.get("status") == "ok"]
        if not ok_results:
            logger.warning("所有窗口均无有效结果")
            return

        ic_values = [r["ic_mean"] for r in ok_results if r.get("ic_mean") is not None]
        icir_values = [r["icir"] for r in ok_results if r.get("icir") is not None]

        logger.info("\n" + "=" * 60)
        logger.info("Walk-Forward 汇总")
        logger.info("=" * 60)
        logger.info(f"有效窗口数: {len(ok_results)} / {len(self.results)}")
        if ic_values:
            logger.info(f"IC 均值: {np.mean(ic_values):.4f} ± {np.std(ic_values):.4f}")
        if icir_values:
            logger.info(f"ICIR 均值: {np.mean(icir_values):.4f}")

    def get_results_df(self) -> pd.DataFrame:
        """Return per-window results as a DataFrame for analysis."""
        if not self.results:
            return pd.DataFrame()
        rows = []
        for r in self.results:
            rows.append({
                "window_id": r.get("window_id"),
                "test_period": r.get("test_period"),
                "status": r.get("status"),
                "ic_mean": r.get("ic_mean"),
                "icir": r.get("icir"),
                "long_short_return": r.get("long_short_return"),
                "n_samples": r.get("n_samples"),
                "elapsed_sec": r.get("elapsed_sec"),
            })
        return pd.DataFrame(rows)
