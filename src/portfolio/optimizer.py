"""组合优化器 — CAA / 等权 / 风险平价

P1-05: Classical Asset Allocation (Keller, Butler & Kipnis 2015)
- 纯多头 MVO (消除 Markowitz 不稳定性)
- 1/3/6/12 月动量平均作为收益估计
- 12 月滚动协方差
- 单资产权重上限 (默认 25%, 现金类不限)
- SLSQP 求解 (等效 CLA 在纯多头约束下的结果)
"""
from __future__ import annotations


import numpy as np
import pandas as pd
from scipy.optimize import minimize

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)

_TRADING_DAYS_PER_MONTH = 21
_MOMENTUM_MONTHS = (1, 3, 6, 12)


class CAAOptimizer:
    """Classical Asset Allocation — momentum-driven long-only MVO.

    Parameters
    ----------
    target_vol : float
        目标年化波动率, 用于波动率约束 (默认 10%).
    cap : float
        风险资产单一权重上限 (默认 25%).
    cash_assets : list[str] | None
        现金类资产代码列表, 权重不受 cap 限制.
    """

    def __init__(
        self,
        target_vol: float | None = None,
        cap: float | None = None,
        cash_assets: list[str] | None = None,
    ):
        cfg = settings.portfolio
        self.target_vol = target_vol if target_vol is not None else cfg.caa_target_vol
        self.cap = cap if cap is not None else cfg.caa_cap
        if cash_assets is not None:
            self.cash_assets = set(cash_assets)
        else:
            self.cash_assets = set(cfg.caa_cash_assets)

    def optimize(self, prices: pd.DataFrame) -> dict[str, float]:
        """根据历史价格序列计算最优权重.

        Parameters
        ----------
        prices : pd.DataFrame
            行 = 日期 (升序), 列 = 资产代码, 值 = 收盘价.

        Returns
        -------
        dict[str, float]
            {资产代码: 权重}, 所有权重 >= 0, 加总 = 1.
        """
        if prices.shape[0] < _TRADING_DAYS_PER_MONTH * 2:
            logger.warning("价格数据不足 2 个月, 退化为等权")
            n = len(prices.columns)
            return {col: 1.0 / n for col in prices.columns}

        expected_returns = self._estimate_returns(prices)
        returns = prices.pct_change().dropna()
        cov_matrix = returns.iloc[-_TRADING_DAYS_PER_MONTH * 12 :].cov() * 252

        assets = list(prices.columns)
        weight_bounds = []
        for a in assets:
            if a in self.cash_assets:
                weight_bounds.append((0.0, 1.0))
            else:
                weight_bounds.append((0.0, self.cap))

        weights = self._cla_solve(cov_matrix, expected_returns, weight_bounds)
        return dict(zip(assets, weights))

    def _estimate_returns(self, prices: pd.DataFrame) -> pd.Series:
        """动量收益估计: 1/3/6/12 月收益率的等权平均."""
        mom_returns = []
        for m in _MOMENTUM_MONTHS:
            lookback = _TRADING_DAYS_PER_MONTH * m
            if prices.shape[0] > lookback:
                ret = prices.iloc[-1] / prices.iloc[-lookback] - 1.0
            else:
                ret = prices.iloc[-1] / prices.iloc[0] - 1.0
            mom_returns.append(ret)
        return pd.concat(mom_returns, axis=1).mean(axis=1)

    def _cla_solve(
        self,
        cov_matrix: pd.DataFrame,
        expected_returns: pd.Series,
        weight_bounds: list[tuple[float, float]],
    ) -> np.ndarray:
        """SLSQP 求解纯多头 MVO (最大化 Sharpe).

        目标: max (w'μ) / sqrt(w'Σw)  等价于  min -w'μ  s.t. w'Σw <= σ²_target
        """
        n = len(expected_returns)
        mu = expected_returns.values.astype(float)
        sigma = cov_matrix.values.astype(float)

        sigma = (sigma + sigma.T) / 2.0
        eigvals = np.linalg.eigvalsh(sigma)
        if eigvals.min() < 0:
            sigma += (-eigvals.min() + 1e-8) * np.eye(n)

        x0 = np.ones(n) / n

        constraints = [
            {"type": "eq", "fun": lambda w: np.sum(w) - 1.0},
            {
                "type": "ineq",
                "fun": lambda w: self.target_vol**2 - float(w @ sigma @ w),
            },
        ]

        def neg_return(w: np.ndarray) -> float:
            return -float(w @ mu)

        result = minimize(
            neg_return,
            x0,
            method="SLSQP",
            bounds=weight_bounds,
            constraints=constraints,
            options={"maxiter": 1000, "ftol": 1e-12},
        )

        if result.success:
            weights = np.maximum(result.x, 0.0)
        else:
            logger.warning("SLSQP 未收敛 (%s), 使用等权回退", result.message)
            weights = np.ones(n) / n

        total = weights.sum()
        if total > 0:
            weights /= total
        return weights


class RiskParityOptimizer:
    """等风险贡献 (ERC) — 每个资产对组合风险的贡献相等."""

    def optimize(self, prices: pd.DataFrame) -> dict[str, float]:
        """迭代算法求解风险平价权重.

        Parameters
        ----------
        prices : pd.DataFrame
            行 = 日期, 列 = 资产代码.

        Returns
        -------
        dict[str, float]
            {资产代码: 权重}
        """
        returns = prices.pct_change().dropna()
        cov = returns.cov().values * 252
        n = cov.shape[0]
        assets = list(prices.columns)

        cov = (cov + cov.T) / 2.0
        eigvals = np.linalg.eigvalsh(cov)
        if eigvals.min() < 0:
            cov += (-eigvals.min() + 1e-8) * np.eye(n)

        x0 = np.ones(n) / n

        def risk_budget_objective(w: np.ndarray) -> float:
            port_var = w @ cov @ w
            if port_var <= 0:
                return 1e10
            marginal = cov @ w
            risk_contrib = w * marginal
            target_rc = port_var / n
            return float(np.sum((risk_contrib - target_rc) ** 2))

        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1.0}]
        bounds = [(0.0, 1.0)] * n

        result = minimize(
            risk_budget_objective,
            x0,
            method="SLSQP",
            bounds=bounds,
            constraints=constraints,
            options={"maxiter": 1000, "ftol": 1e-14},
        )

        if result.success:
            weights = np.maximum(result.x, 0.0)
        else:
            logger.warning("RiskParity 未收敛, 使用等权回退")
            weights = np.ones(n) / n

        total = weights.sum()
        if total > 0:
            weights /= total

        return dict(zip(assets, weights.tolist()))


class PortfolioOptimizer:
    """门面: 根据配置分发到具体优化器."""

    def __init__(self, method: str | None = None):
        self.method = method or settings.portfolio.optimizer_method

    def optimize(self, prices: pd.DataFrame, **kwargs) -> dict[str, float]:
        if self.method == "caa":
            return CAAOptimizer(**kwargs).optimize(prices)
        if self.method == "risk_parity":
            return RiskParityOptimizer().optimize(prices)
        n = len(prices.columns)
        return {col: 1.0 / n for col in prices.columns}
