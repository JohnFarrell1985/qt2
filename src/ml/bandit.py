"""Thompson Sampling Bandit for factor vs model iteration decision.

Two-arm linear contextual bandit:
  - "factor" arm: factor mining / feature engineering iteration
  - "model" arm: model hyperparameter tuning iteration

Uses 8-dimensional quantitative metrics vector as context and a Gaussian
posterior with linear model for Thompson Sampling.

Reference: RD-Agent(Q) paper (arXiv:2505.15155)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class BanditMetrics:
    """8-dimensional quantitative metrics vector (from RD-Agent paper)."""

    ic: float = 0.0
    icir: float = 0.0
    rank_ic: float = 0.0
    rank_icir: float = 0.0
    annual_return: float = 0.0
    information_ratio: float = 0.0
    max_drawdown: float = 0.0
    sharpe: float = 0.0

    WEIGHTS: tuple[float, ...] = (0.1, 0.1, 0.05, 0.05, 0.25, 0.15, 0.1, 0.2)

    def to_reward(self) -> float:
        """Weighted sum -> scalar reward. Note: mdd is negated."""
        values = [
            self.ic,
            self.icir,
            self.rank_ic,
            self.rank_icir,
            self.annual_return,
            self.information_ratio,
            -self.max_drawdown,
            self.sharpe,
        ]
        return sum(w * v for w, v in zip(self.WEIGHTS, values))

    def to_vector(self) -> np.ndarray:
        """Return 8-dim context vector (mdd negated so higher = better)."""
        return np.array([
            self.ic,
            self.icir,
            self.rank_ic,
            self.rank_icir,
            self.annual_return,
            self.information_ratio,
            -self.max_drawdown,
            self.sharpe,
        ])


class LinearThompsonBandit:
    """Linear Thompson Sampling two-arm bandit.

    Arms: ``"factor"`` (factor mining) vs ``"model"`` (model tuning).
    Context: 8-dim metrics vector.
    Uses Gaussian posterior with linear model.

    For each arm *a*, we maintain:
      - B_a: precision matrix (d x d), initialized to I / prior_variance
      - f_a: cumulative context*reward vector (d,)

    Posterior mean:  mu_hat = B_inv @ f
    Posterior cov:   B_inv

    Thompson Sampling: sample theta ~ N(mu_hat, B_inv), pick argmax(context @ theta).
    """

    ARM_NAMES = ["factor", "model"]

    def __init__(self, n_features: int = 8, prior_variance: float = 1.0):
        if n_features <= 0:
            raise ValueError("n_features must be positive")
        if prior_variance <= 0:
            raise ValueError("prior_variance must be positive")
        self.n_features = n_features
        self.prior_variance = prior_variance
        self.arms: dict[str, dict] = {}
        for arm in self.ARM_NAMES:
            self.arms[arm] = {
                "B": np.eye(n_features) / prior_variance,
                "f": np.zeros(n_features),
                "n_pulls": 0,
            }

    def select_arm(self, context: np.ndarray) -> str:
        """Thompson Sampling: sample from posterior, pick arm with higher expected reward."""
        context = np.asarray(context, dtype=float).ravel()
        if len(context) != self.n_features:
            raise ValueError(
                f"Context dimension {len(context)} != n_features {self.n_features}"
            )

        sampled_rewards: dict[str, float] = {}
        for arm_name, arm_data in self.arms.items():
            B_inv = np.linalg.inv(arm_data["B"])
            mu_hat = B_inv @ arm_data["f"]
            theta_sample = np.random.multivariate_normal(mu_hat, B_inv)
            sampled_rewards[arm_name] = float(context @ theta_sample)

        chosen = max(sampled_rewards, key=sampled_rewards.get)  # type: ignore[arg-type]
        logger.debug(
            f"Bandit select: {sampled_rewards} -> {chosen}"
        )
        return chosen

    def update(self, arm: str, context: np.ndarray, reward: float) -> None:
        """Update posterior after observing reward."""
        if arm not in self.arms:
            raise ValueError(f"Unknown arm: {arm}. Must be one of {self.ARM_NAMES}")
        context = np.asarray(context, dtype=float).ravel()
        if len(context) != self.n_features:
            raise ValueError(
                f"Context dimension {len(context)} != n_features {self.n_features}"
            )

        self.arms[arm]["B"] += np.outer(context, context)
        self.arms[arm]["f"] += context * reward
        self.arms[arm]["n_pulls"] += 1

    def get_stats(self) -> dict:
        """Return arm pull counts and estimated parameters."""
        stats: dict = {}
        for arm_name, arm_data in self.arms.items():
            B_inv = np.linalg.inv(arm_data["B"])
            mu_hat = B_inv @ arm_data["f"]
            stats[arm_name] = {
                "n_pulls": arm_data["n_pulls"],
                "mu_hat": mu_hat.tolist(),
                "posterior_trace": float(np.trace(B_inv)),
            }
        return stats


class IterationController:
    """Decision controller integrating bandit with the iteration engine.

    Usage::

        controller = IterationController()
        for iteration in range(max_iter):
            metrics = run_iteration(...)
            bandit_metrics = BanditMetrics(ic=..., sharpe=..., ...)
            next_action = controller.decide(bandit_metrics)
            # next_action is "factor" or "model"
    """

    def __init__(self, bandit: LinearThompsonBandit | None = None):
        self.bandit = bandit or LinearThompsonBandit()
        self.history: list[dict] = []
        self._last_action: str | None = None
        self._last_context: np.ndarray | None = None

    def decide(self, metrics: BanditMetrics) -> str:
        """Record previous result (if any) and decide next action.

        If this is not the first call, the given *metrics* is treated as the
        outcome of ``self._last_action`` and used to update the bandit.
        """
        context = metrics.to_vector()
        reward = metrics.to_reward()

        if self._last_action is not None and self._last_context is not None:
            self.bandit.update(self._last_action, self._last_context, reward)

        action = self.bandit.select_arm(context)
        self._last_action = action
        self._last_context = context.copy()

        self.history.append({
            "action": action,
            "reward": reward,
            "context": context.tolist(),
            "timestamp": datetime.now().isoformat(),
        })
        logger.info(f"Bandit 决策: {action} (reward={reward:.4f})")
        return action

    def record(self, action: str, metrics: BanditMetrics) -> None:
        """Explicitly record action and observed metrics (manual mode)."""
        context = metrics.to_vector()
        reward = metrics.to_reward()
        self.bandit.update(action, context, reward)
        self.history.append({
            "action": action,
            "reward": reward,
            "context": context.tolist(),
            "timestamp": datetime.now().isoformat(),
        })

    def get_summary(self) -> dict:
        """Return controller history summary."""
        factor_count = sum(1 for h in self.history if h["action"] == "factor")
        model_count = sum(1 for h in self.history if h["action"] == "model")
        rewards = [h["reward"] for h in self.history]
        return {
            "total_iterations": len(self.history),
            "factor_pulls": factor_count,
            "model_pulls": model_count,
            "mean_reward": float(np.mean(rewards)) if rewards else 0.0,
            "bandit_stats": self.bandit.get_stats(),
        }
