"""Thompson Sampling 双臂 Bandit (P2-18)

决定每轮迭代的方向: "factor" (挖掘新因子) vs "model" (优化模型超参)。
8 维指标向量作为上下文: IC, ICIR, Rank IC, Rank ICIR, 年化收益, IR, 最大回撤, Sharpe。

参考: RD-Agent rdagent/scenarios/qlib/proposal/bandit.py
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from src.common.logger import get_logger

logger = get_logger(__name__)

ARM_FACTOR = "factor"
ARM_MODEL = "model"
ARMS = [ARM_FACTOR, ARM_MODEL]

DEFAULT_WEIGHTS = np.array([0.1, 0.1, 0.05, 0.05, 0.25, 0.15, 0.1, 0.2])


class LinearThompsonTwoArm:
    """Linear Thompson Sampling for 2-arm contextual bandit

    每个 arm 维护一个 Bayesian 线性回归模型:
    reward ∼ N(θ'x, σ²), θ ∼ N(μ, Σ)

    Args:
        n_features: 上下文维度 (默认 8: IC/ICIR/RankIC/RankICIR/AnnRet/IR/MaxDD/Sharpe)
        lambda_prior: 先验精度 (Ridge 正则化)
    """

    def __init__(self, n_features: int = 8, lambda_prior: float = 1.0):
        self.n_features = n_features
        self.lambda_prior = lambda_prior
        self._B = {arm: lambda_prior * np.eye(n_features) for arm in ARMS}
        self._mu = {arm: np.zeros(n_features) for arm in ARMS}
        self._f = {arm: np.zeros(n_features) for arm in ARMS}
        self._rng = np.random.default_rng(42)
        self._history: List[Tuple[str, float, np.ndarray]] = []

    def next_arm(self, context: Optional[np.ndarray] = None) -> str:
        """选择下一轮动作

        Args:
            context: 上一轮的 8 维指标向量, None 则随机探索

        Returns:
            "factor" 或 "model"
        """
        if context is None:
            return self._rng.choice(ARMS)

        x = np.asarray(context, dtype=float).flatten()
        if len(x) != self.n_features:
            logger.warning("上下文维度不匹配: %d vs %d", len(x), self.n_features)
            return self._rng.choice(ARMS)

        scores = {}
        for arm in ARMS:
            B_inv = np.linalg.inv(self._B[arm])
            mu = B_inv @ self._f[arm]
            theta_sample = self._rng.multivariate_normal(mu, B_inv)
            scores[arm] = float(theta_sample @ x)

        chosen = max(scores, key=scores.get)
        logger.debug("Bandit 选择: %s (factor=%.4f, model=%.4f)", chosen, scores[ARM_FACTOR], scores[ARM_MODEL])
        return chosen

    def update(self, arm: str, reward: float, context: np.ndarray) -> None:
        """更新 arm 的后验分布

        Args:
            arm: 执行的动作
            reward: 标量奖励 (加权指标得分)
            context: 本轮的 8 维上下文
        """
        x = np.asarray(context, dtype=float).flatten()
        self._B[arm] += np.outer(x, x)
        self._f[arm] += reward * x
        self._history.append((arm, reward, x.copy()))
        logger.debug("Bandit 更新 arm=%s reward=%.4f", arm, reward)

    def compute_reward(self, metrics: dict, weights: Optional[np.ndarray] = None) -> float:
        """从指标字典计算标量奖励"""
        if weights is None:
            weights = DEFAULT_WEIGHTS
        keys = ["ic", "icir", "rank_ic", "rank_icir", "ann_return", "ir", "max_drawdown", "sharpe"]
        vec = np.array([metrics.get(k, 0.0) for k in keys], dtype=float)
        vec[6] = -abs(vec[6])
        return float(weights @ vec)

    @property
    def total_pulls(self) -> dict:
        return {arm: sum(1 for h in self._history if h[0] == arm) for arm in ARMS}
