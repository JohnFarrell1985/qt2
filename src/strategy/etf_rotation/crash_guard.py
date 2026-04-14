"""崩盘保护机制 — 三重护卫

BreadthMomentumGuard: 金丝雀资产动量过滤
AbsoluteMomentumGuard: 风险池绝对动量判断
VolatilityGuard: 波动率百分位门控
CrashGuard: 组合护卫 (取最大现金比例)
"""
import pandas as pd

from src.common.logger import get_logger
from src.strategy.etf_rotation.momentum import calc_13612w

logger = get_logger(__name__)


class BreadthMomentumGuard:
    """金丝雀护卫 — 基于 canary 资产的 13612W 动量

    负动量的金丝雀数量 / 总数 = cash_fraction
    全部为负 → 100% 现金; 全部为正 → 0% 现金
    """

    def evaluate(self, canary_prices: pd.DataFrame) -> float:
        if canary_prices.empty or canary_prices.shape[1] == 0:
            return 1.0

        mom = calc_13612w(canary_prices)
        n_total = len(mom)
        if n_total == 0:
            return 1.0

        n_negative = (mom < 0).sum()
        return float(n_negative / n_total)


class AbsoluteMomentumGuard:
    """绝对动量护卫 — 所有风险 ETF 动量为负则全仓防御

    Returns:
        1.0 如果全部为负 (100% 防御), 否则 0.0
    """

    def evaluate(self, risk_prices: pd.DataFrame) -> float:
        if risk_prices.empty or risk_prices.shape[1] == 0:
            return 1.0

        mom = calc_13612w(risk_prices)
        if mom.empty:
            return 1.0

        if (mom < 0).all():
            return 1.0
        return 0.0


class VolatilityGuard:
    """波动率门控 — 基于波动率历史百分位缩减仓位

    vol_pct > 0.9 → 0.10 仓位 (90% 现金)
    vol_pct > 0.7 → 0.40 仓位
    vol_pct > 0.5 → 0.70 仓位
    else          → 1.00 满仓
    """

    THRESHOLDS = [
        (0.9, 0.90),
        (0.7, 0.60),
        (0.5, 0.30),
    ]

    def evaluate(self, prices: pd.DataFrame, window: int = 252) -> float:
        if prices.empty or len(prices) < 20:
            return 0.0

        returns = prices.pct_change().dropna()
        if returns.empty:
            return 0.0

        current_vol = returns.iloc[-20:].std().mean()
        hist_window = min(len(returns), window)
        rolling_vol = returns.iloc[-hist_window:].rolling(20).std().mean(axis=1).dropna()

        if rolling_vol.empty:
            return 0.0

        vol_pct = float((rolling_vol < current_vol).mean())

        for threshold, cash_frac in self.THRESHOLDS:
            if vol_pct > threshold:
                logger.debug("VolatilityGuard: vol_pct=%.2f → cash=%.0f%%", vol_pct, cash_frac * 100)
                return cash_frac

        return 0.0


class CrashGuard:
    """组合护卫 — 启用的子护卫取最大现金比例"""

    def __init__(
        self,
        enable_breadth: bool = True,
        enable_absolute: bool = True,
        enable_volatility: bool = True,
    ):
        self._guards: list[tuple[str, object]] = []
        if enable_breadth:
            self._guards.append(("breadth", BreadthMomentumGuard()))
        if enable_absolute:
            self._guards.append(("absolute", AbsoluteMomentumGuard()))
        if enable_volatility:
            self._guards.append(("volatility", VolatilityGuard()))

    def evaluate(
        self,
        canary_prices: pd.DataFrame,
        risk_prices: pd.DataFrame,
        all_prices: pd.DataFrame,
    ) -> float:
        """返回综合现金比例 (0.0 = 满仓, 1.0 = 全现金)"""
        cash_fractions: list[float] = []

        for name, guard in self._guards:
            if name == "breadth":
                frac = guard.evaluate(canary_prices)
            elif name == "absolute":
                frac = guard.evaluate(risk_prices)
            elif name == "volatility":
                frac = guard.evaluate(all_prices)
            else:
                continue
            logger.debug("CrashGuard.%s → cash_fraction=%.2f", name, frac)
            cash_fractions.append(frac)

        if not cash_fractions:
            return 0.0

        result = max(cash_fractions)
        if result > 0:
            logger.info("CrashGuard 触发: cash_fraction=%.2f", result)
        return result
