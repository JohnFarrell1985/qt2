"""RD-Agent 联合迭代主循环 (P2-18)

LLM + Bandit + Trace 架构:
1. Bandit 选择方向 (factor / model)
2. LLM 生成假设 + 代码 (可选, 降级为规则引擎)
3. 执行回测验证
4. 反馈更新 Bandit + Trace

参考: RD-Agent rdagent/app/qlib_rd_loop/quant.py (QuantRDLoop)
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import numpy as np

from src.common.config import settings
from src.common.logger import get_logger
from src.ml.bandit import LinearThompsonTwoArm, DEFAULT_WEIGHTS, ARM_FACTOR, ARM_MODEL
from src.ml.experiment_tracker import ExperimentTrace

logger = get_logger(__name__)


class SimpleRDLoop:
    """简化版 RD 联合迭代循环

    不依赖完整 RD-Agent 框架, 使用本项目已有组件。
    """

    def __init__(
        self,
        bandit: Optional[LinearThompsonTwoArm] = None,
        trace: Optional[ExperimentTrace] = None,
        factor_proposer: Optional[Callable] = None,
        model_proposer: Optional[Callable] = None,
        evaluator: Optional[Callable] = None,
        max_iterations: int = 20,
    ):
        self.bandit = bandit or LinearThompsonTwoArm()
        self.trace = trace or ExperimentTrace()
        self._propose_factor = factor_proposer or self._default_factor_proposer
        self._propose_model = model_proposer or self._default_model_proposer
        self._evaluate = evaluator
        self.max_iterations = max_iterations
        self.sota_metrics: Dict[str, float] = {}

    def iterate(self, n_rounds: Optional[int] = None) -> List[Dict[str, Any]]:
        """运行迭代循环

        Args:
            n_rounds: 迭代轮数, None 则使用 max_iterations

        Returns:
            每轮结果列表
        """
        rounds = n_rounds or self.max_iterations
        results = []

        for i in range(rounds):
            prev = self.trace.last_metrics()
            context = self._metrics_to_vec(prev) if prev else None
            action = self.bandit.next_arm(context)

            logger.info("RD Loop 第 %d 轮: action=%s", i + 1, action)

            try:
                if action == ARM_FACTOR:
                    proposal = self._propose_factor(self.trace)
                else:
                    proposal = self._propose_model(self.trace)

                if self._evaluate:
                    metrics = self._evaluate(proposal, action)
                else:
                    metrics = proposal.get("metrics", {})

                reward = self.bandit.compute_reward(metrics)
                success = reward > self.bandit.compute_reward(self.sota_metrics) if self.sota_metrics else reward > 0

                if success:
                    self.sota_metrics = metrics.copy()

                record = self.trace.append(
                    action=action,
                    hypothesis=proposal.get("hypothesis", ""),
                    implementation=proposal.get("implementation", ""),
                    metrics=metrics,
                    reward=reward,
                    success=success,
                )

                if context is not None:
                    self.bandit.update(action, reward, context)
                else:
                    self.bandit.update(action, reward, self._metrics_to_vec(metrics))

                results.append({
                    "round": i + 1,
                    "action": action,
                    "reward": reward,
                    "success": success,
                    "metrics": metrics,
                })

            except Exception as e:
                logger.error("RD Loop 第 %d 轮异常: %s", i + 1, e)
                self.trace.append(
                    action=action,
                    hypothesis=f"error: {e}",
                    reward=-1.0,
                    success=False,
                )

        logger.info(
            "RD Loop 完成 %d 轮: factor=%d, model=%d, SOTA=%s",
            len(results),
            self.bandit.total_pulls.get(ARM_FACTOR, 0),
            self.bandit.total_pulls.get(ARM_MODEL, 0),
            self.sota_metrics,
        )
        return results

    @staticmethod
    def _metrics_to_vec(metrics: Dict[str, float]) -> np.ndarray:
        keys = ["ic", "icir", "rank_ic", "rank_icir", "ann_return", "ir", "max_drawdown", "sharpe"]
        return np.array([metrics.get(k, 0.0) for k in keys], dtype=float)

    @staticmethod
    def _default_factor_proposer(trace: ExperimentTrace) -> Dict[str, Any]:
        """默认因子提议器 — 随机因子组合 (LLM 不可用时的规则降级)"""
        rng = np.random.default_rng()
        n_factors = rng.integers(3, 10)
        hypothesis = f"随机组合 {n_factors} 个因子进行探索"
        return {
            "hypothesis": hypothesis,
            "implementation": f"random_{n_factors}_factors",
            "metrics": {
                "ic": float(rng.normal(0.02, 0.01)),
                "icir": float(rng.normal(0.3, 0.1)),
                "rank_ic": float(rng.normal(0.02, 0.01)),
                "rank_icir": float(rng.normal(0.3, 0.1)),
                "ann_return": float(rng.normal(0.1, 0.05)),
                "ir": float(rng.normal(0.5, 0.2)),
                "max_drawdown": float(rng.uniform(0.05, 0.3)),
                "sharpe": float(rng.normal(0.8, 0.3)),
            },
        }

    @staticmethod
    def _default_model_proposer(trace: ExperimentTrace) -> Dict[str, Any]:
        """默认模型提议器 — 网格搜索超参"""
        rng = np.random.default_rng()
        lr = float(rng.choice([0.01, 0.03, 0.05, 0.1]))
        leaves = int(rng.choice([31, 63, 127]))
        hypothesis = f"尝试 lr={lr}, leaves={leaves}"
        return {
            "hypothesis": hypothesis,
            "implementation": f"lgb_lr{lr}_leaves{leaves}",
            "metrics": {
                "ic": float(rng.normal(0.025, 0.01)),
                "icir": float(rng.normal(0.35, 0.1)),
                "rank_ic": float(rng.normal(0.025, 0.01)),
                "rank_icir": float(rng.normal(0.35, 0.1)),
                "ann_return": float(rng.normal(0.12, 0.05)),
                "ir": float(rng.normal(0.6, 0.2)),
                "max_drawdown": float(rng.uniform(0.05, 0.25)),
                "sharpe": float(rng.normal(1.0, 0.3)),
            },
        }
