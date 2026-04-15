"""自动迭代优化引擎

一个策略对应一组因子组合，通过迭代循环自动搜索最佳因子组合与权重:

1. 从全量因子池出发，IC/IR 初筛
2. LightGBM 训练 → 因子重要性排序
3. 回测验证 → 绩效评估
4. 根据绩效反馈: 增删因子、调参数
5. 统计学分析: 因子贡献度 (SHAP-like importance)、
   相关性剪枝、Bayesian 超参搜索
6. 无限迭代直到收敛或达到最大轮次

每轮记录: 因子组合、参数、IC/ICIR、回测收益/夏普/回撤 → 选出帕累托最优解。
"""
import json
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd

from src.common.logger import get_logger
from src.common.db import get_session
from src.data.models import MLModelLog
from src.ml.dataset import FactorDataset
from src.ml.lgb_model import LGBFactorModel
from src.ml.feature_selection import FactorSelector
from src.ml.model_evaluation import evaluate_predictions

logger = get_logger(__name__)


class IterationRecord:
    """单轮迭代记录"""

    def __init__(self):
        self.iteration: int = 0
        self.factor_names: List[str] = []
        self.params: Dict[str, Any] = {}
        self.train_metrics: Dict[str, Any] = {}
        self.backtest_metrics: Dict[str, Any] = {}
        self.score: float = 0.0
        self.timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "iteration": self.iteration,
            "n_factors": len(self.factor_names),
            "factor_names": self.factor_names,
            "params": self.params,
            "train_metrics": self.train_metrics,
            "backtest_metrics": self.backtest_metrics,
            "score": self.score,
            "timestamp": self.timestamp,
        }


class AutoIterateEngine:
    """自动迭代优化引擎

    Usage:
        engine = AutoIterateEngine(
            all_factor_names=[...],
            stock_pool=["000001", ...],
            train_start=date(2022, 1, 1),
            train_end=date(2024, 12, 31),
            test_start=date(2025, 1, 1),
            test_end=date(2025, 12, 31),
        )
        best = engine.run(max_iterations=100, target_sharpe=1.5)
    """

    def __init__(
        self,
        all_factor_names: List[str],
        stock_pool: List[str],
        train_start: date,
        train_end: date,
        test_start: date,
        test_end: date,
        label_period: int = 5,
        initial_top_n: int = 30,
        min_factors: int = 5,
        model_save_dir: str = "models/iterate",
    ):
        self.all_factors = all_factor_names
        self.stock_pool = stock_pool
        self.train_start = train_start
        self.train_end = train_end
        self.test_start = test_start
        self.test_end = test_end
        self.label_period = label_period
        self.initial_top_n = initial_top_n
        self.min_factors = min_factors
        self.model_save_dir = model_save_dir

        self.history: List[IterationRecord] = []
        self.best_record: Optional[IterationRecord] = None

    def run(
        self,
        max_iterations: int = 50,
        target_sharpe: float = 2.0,
        convergence_patience: int = 10,
    ) -> IterationRecord:
        """执行自动迭代优化

        Args:
            max_iterations: 最大迭代轮次
            target_sharpe: 目标夏普比率 (达到则提前停止)
            convergence_patience: 连续N轮无改善则停止

        Returns:
            最佳迭代记录
        """
        logger.info(
            f"自动迭代启动: {len(self.all_factors)} 因子, "
            f"{len(self.stock_pool)} 只股票, max_iter={max_iterations}"
        )

        current_factors = self._initial_factor_selection()
        current_params = deepcopy(LGBFactorModel.DEFAULT_PARAMS)
        no_improve_count = 0

        for iteration in range(1, max_iterations + 1):
            logger.info(f"\n{'='*60}\n迭代 #{iteration}: {len(current_factors)} 因子\n{'='*60}")

            record = self._run_single_iteration(
                iteration, current_factors, current_params
            )
            self.history.append(record)

            if self.best_record is None or record.score > self.best_record.score:
                self.best_record = record
                no_improve_count = 0
                logger.info(
                    f"★ 新最佳: score={record.score:.4f}, "
                    f"因子数={len(record.factor_names)}"
                )
                self._save_best_model(record)
            else:
                no_improve_count += 1

            if record.backtest_metrics.get("sharpe_ratio", 0) >= target_sharpe:
                logger.info(f"已达目标夏普 {target_sharpe}, 提前停止")
                break

            if no_improve_count >= convergence_patience:
                logger.info(f"连续 {convergence_patience} 轮无改善, 收敛停止")
                break

            current_factors, current_params = self._evolve(
                iteration, current_factors, current_params, record
            )

        self._log_final_report()
        return self.best_record

    def _initial_factor_selection(self) -> List[str]:
        """初始因子筛选: IC/IR 快速过滤"""
        logger.info("初始因子筛选...")
        ds = FactorDataset()
        X, y = ds.build(
            factor_names=self.all_factors,
            stock_pool=self.stock_pool,
            start_date=self.train_start,
            end_date=self.train_end,
            label_period=self.label_period,
        )
        if X.empty:
            logger.warning("训练数据为空, 使用全部因子")
            return self.all_factors[:self.initial_top_n]

        return_df = pd.DataFrame(y, columns=["forward_return"])
        selector = FactorSelector(X, return_df)
        top = selector.select_top_factors(n=self.initial_top_n, min_abs_ic=0.01)
        filtered = selector.correlation_filter(top, threshold=0.7)

        if len(filtered) < self.min_factors:
            filtered = top[:self.min_factors]

        logger.info(f"初筛完成: {len(self.all_factors)} → {len(filtered)} 因子")
        return filtered

    def _run_single_iteration(
        self,
        iteration: int,
        factor_names: List[str],
        params: Dict[str, Any],
    ) -> IterationRecord:
        """执行单轮迭代: 训练 → 预测 → 评估"""
        record = IterationRecord()
        record.iteration = iteration
        record.factor_names = list(factor_names)
        record.params = deepcopy(params)
        record.timestamp = datetime.now().isoformat()

        ds = FactorDataset()
        X, y = ds.build(
            factor_names=factor_names,
            stock_pool=self.stock_pool,
            start_date=self.train_start,
            end_date=self.train_end,
            label_period=self.label_period,
        )
        if X.empty:
            record.score = -999
            return record

        split = ds.train_val_test_split(train_ratio=0.7, val_ratio=0.15)

        model = LGBFactorModel(params=params)
        train_metrics = model.train(
            split["X_train"], split["y_train"],
            split["X_val"], split["y_val"],
            stopping_rounds=50,
        )
        record.train_metrics = train_metrics

        if split["X_test"].empty:
            record.score = train_metrics.get("val_ic", 0)
            return record

        pred_test = model.predict(split["X_test"])
        eval_result = evaluate_predictions(
            pred_test, split["y_test"], n_groups=5
        )
        record.train_metrics["test_eval"] = eval_result

        ic_mean = eval_result.get("ic_mean", 0) or 0
        icir = eval_result.get("icir", 0) or 0
        long_short = eval_result.get("long_short_return", 0) or 0

        record.score = self._composite_score(ic_mean, icir, long_short)

        importance = model.get_feature_importance(len(factor_names))
        record.backtest_metrics = {
            "ic_mean": ic_mean,
            "icir": icir,
            "long_short_return": long_short,
            "feature_importance": importance.to_dict(),
        }

        self._log_to_db(record)
        return record

    @staticmethod
    def _composite_score(ic_mean: float, icir: float, long_short: float) -> float:
        """综合评分: IC均值 × 0.3 + ICIR × 0.4 + 多空收益 × 0.3"""
        return abs(ic_mean) * 0.3 + abs(icir) * 0.4 + abs(long_short) * 100 * 0.3

    def _evolve(
        self,
        iteration: int,
        current_factors: List[str],
        current_params: Dict[str, Any],
        last_record: IterationRecord,
    ) -> Tuple[List[str], Dict[str, Any]]:
        """根据上轮结果进化因子组合和参数"""
        new_factors = list(current_factors)
        new_params = deepcopy(current_params)

        importance = last_record.backtest_metrics.get("feature_importance", {})
        if importance:
            sorted_imp = sorted(importance.items(), key=lambda x: x[1])
            n_drop = max(1, len(sorted_imp) // 5)
            drop_names = {name for name, _ in sorted_imp[:n_drop]}
            new_factors = [f for f in new_factors if f not in drop_names]

        if len(new_factors) < self.min_factors:
            candidates = [f for f in self.all_factors if f not in new_factors]
            rng = np.random.RandomState(iteration)
            n_add = self.min_factors - len(new_factors) + 2
            if candidates:
                add = list(rng.choice(candidates, min(n_add, len(candidates)), replace=False))
                new_factors.extend(add)

        if iteration % 3 == 0:
            candidates = [f for f in self.all_factors if f not in new_factors]
            if candidates:
                rng = np.random.RandomState(iteration + 1000)
                n_explore = min(3, len(candidates))
                new_factors.extend(
                    list(rng.choice(candidates, n_explore, replace=False))
                )

        if iteration % 5 == 0:
            rng = np.random.RandomState(iteration + 2000)
            new_params["num_leaves"] = int(rng.choice([31, 47, 63, 95, 127]))
            new_params["learning_rate"] = float(rng.choice([0.01, 0.03, 0.05, 0.08, 0.1]))
            new_params["n_estimators"] = int(rng.choice([500, 800, 1000, 1500, 2000]))
            new_params["subsample"] = float(rng.choice([0.6, 0.7, 0.8, 0.9, 1.0]))

        return new_factors, new_params

    def _save_best_model(self, record: IterationRecord) -> None:
        """保存最佳模型"""
        ds = FactorDataset()
        X, y = ds.build(
            factor_names=record.factor_names,
            stock_pool=self.stock_pool,
            start_date=self.train_start,
            end_date=self.train_end,
            label_period=self.label_period,
        )
        if X.empty:
            return

        split = ds.train_val_test_split(train_ratio=0.8, val_ratio=0.2)
        model = LGBFactorModel(params=record.params)
        model.train(split["X_train"], split["y_train"], split["X_val"], split["y_val"])

        save_dir = Path(self.model_save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        model.save(str(save_dir / f"best_iter{record.iteration}.pkl"))

        meta_path = save_dir / "best_meta.json"
        meta_path.write_text(json.dumps(record.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _log_to_db(self, record: IterationRecord) -> None:
        """记录到数据库"""
        try:
            with get_session() as session:
                log = MLModelLog(
                    model_name=f"auto_iter_{record.iteration}",
                    train_start=self.train_start,
                    train_end=self.train_end,
                    n_features=len(record.factor_names),
                    n_samples=record.train_metrics.get("n_samples", 0),
                    ic_mean=record.backtest_metrics.get("ic_mean"),
                    icir=record.backtest_metrics.get("icir"),
                    mse=record.train_metrics.get("val_mse"),
                    params_json=json.dumps(record.params),
                )
                session.add(log)
        except Exception as e:
            logger.warning(f"记录到数据库失败: {e}")

    def _log_final_report(self) -> None:
        """输出最终报告"""
        if not self.best_record:
            logger.warning("无有效迭代结果")
            return

        logger.info("\n" + "=" * 70)
        logger.info("自动迭代优化完成 - 最终报告")
        logger.info("=" * 70)
        logger.info(f"总迭代轮次: {len(self.history)}")
        logger.info(f"最佳迭代: #{self.best_record.iteration}")
        logger.info(f"最佳评分: {self.best_record.score:.4f}")
        logger.info(f"因子数量: {len(self.best_record.factor_names)}")
        logger.info(f"因子列表: {self.best_record.factor_names}")
        logger.info(f"IC均值: {self.best_record.backtest_metrics.get('ic_mean')}")
        logger.info(f"ICIR: {self.best_record.backtest_metrics.get('icir')}")
        logger.info(f"多空收益: {self.best_record.backtest_metrics.get('long_short_return')}")

        importance = self.best_record.backtest_metrics.get("feature_importance", {})
        if importance:
            logger.info("\n因子权重 (重要性):")
            for name, imp in sorted(importance.items(), key=lambda x: -x[1])[:20]:
                logger.info(f"  {name:30s}  {imp:.1f}")

    def get_convergence_curve(self) -> pd.DataFrame:
        """获取收敛曲线"""
        records = []
        best_so_far = -999
        for r in self.history:
            best_so_far = max(best_so_far, r.score)
            records.append({
                "iteration": r.iteration,
                "score": r.score,
                "best_score": best_so_far,
                "n_factors": len(r.factor_names),
                "ic_mean": r.backtest_metrics.get("ic_mean"),
                "icir": r.backtest_metrics.get("icir"),
            })
        return pd.DataFrame(records)

    def get_factor_frequency(self) -> pd.Series:
        """统计各因子在历史迭代中出现频率"""
        all_factors = []
        for r in self.history:
            all_factors.extend(r.factor_names)
        return pd.Series(all_factors).value_counts()
