"""Regime 门控信号过滤 (Drift Filter)

根据市场 drift/volatility 状态过滤信号。
仅在适合的市场环境下放行对应策略的信号。

References:
  - arXiv:2511.12490 (Drift Regime Gating)
  - arXiv:2603.14288 (Agentic Factor Investing)
"""
from typing import Optional

import numpy as np
import pandas as pd

from src.common.config import settings
from src.common.logger import get_logger
from src.strategy.base import Signal

logger = get_logger(__name__)


class RegimeGate:
    """市场 regime 门控: 根据指数价格序列判断当前 regime,
    然后对信号进行策略-regime 兼容性过滤。
    """

    STRATEGY_REGIME_MAP: dict[str, list[str]] = {
        "momentum":          ["drift_up", "normal"],
        "reversal":          ["drift_down", "high_vol"],
        "low_vol_dividend":  ["normal", "high_vol", "drift_down"],
        "grid_trading":      ["normal"],
        "cb_dual_low":       ["normal", "drift_down", "high_vol"],
        "industry_rotation": ["drift_up", "normal"],
        "moving_average":    ["drift_up", "normal"],
        "lgb_ml":            ["drift_up", "normal"],
        "etf_rotation":      ["drift_up", "normal", "drift_down"],
    }

    def __init__(
        self,
        drift_window: int = 63,
        drift_threshold: float = 0.60,
        vol_percentile_window: int = 252,
        vol_high_pct: float = 0.80,
        custom_map: Optional[dict[str, list[str]]] = None,
    ):
        cfg = settings.regime_gate
        self.drift_window = drift_window if drift_window != 63 else cfg.drift_window
        self.drift_threshold = drift_threshold if drift_threshold != 0.60 else cfg.drift_threshold
        self.vol_percentile_window = (
            vol_percentile_window if vol_percentile_window != 252 else cfg.vol_percentile_window
        )
        self.vol_high_pct = vol_high_pct if vol_high_pct != 0.80 else cfg.vol_high_pct
        self.strategy_map = custom_map or self.STRATEGY_REGIME_MAP

    def detect_regime(self, index_prices: pd.Series) -> str:
        """根据指数价格序列判断市场 regime

        算法:
        1. 计算 drift_window 日收益率的正收益占比 (up_ratio)
        2. 如果 up_ratio >= drift_threshold → drift_up
        3. 如果 up_ratio <= 1 - drift_threshold → drift_down
        4. 计算近期波动率, 与历史 vol_percentile_window 日的分位数比较
        5. 如果 vol_percentile >= vol_high_pct → high_vol
        6. 否则 → normal

        Returns:
            "drift_up" / "drift_down" / "high_vol" / "normal"
        """
        if len(index_prices) < self.drift_window + 1:
            logger.warning(
                f"[RegimeGate] 价格序列长度 {len(index_prices)} "
                f"< 需要 {self.drift_window + 1}, 返回 normal"
            )
            return "normal"

        returns = index_prices.pct_change().dropna()
        recent_returns = returns.iloc[-self.drift_window:]
        up_ratio = (recent_returns > 0).sum() / len(recent_returns)

        if up_ratio >= self.drift_threshold:
            return "drift_up"
        if up_ratio <= 1 - self.drift_threshold:
            return "drift_down"

        recent_vol = recent_returns.std() * np.sqrt(252)
        vol_lookback = min(self.vol_percentile_window, len(returns))
        if vol_lookback >= self.drift_window:
            rolling_vol = returns.rolling(self.drift_window).std() * np.sqrt(252)
            rolling_vol = rolling_vol.dropna()
            if len(rolling_vol) > 0:
                vol_pct = (rolling_vol < recent_vol).sum() / len(rolling_vol)
                if vol_pct >= self.vol_high_pct:
                    return "high_vol"

        return "normal"

    def should_pass(self, signal: Signal, regime: str) -> bool:
        """判断信号是否应在当前 regime 下放行"""
        allowed_regimes = self.strategy_map.get(signal.strategy_name, None)
        if allowed_regimes is None:
            return True
        return regime in allowed_regimes

    def filter_signals(self, signals: list[Signal], regime: str) -> list[Signal]:
        """过滤不适合当前 regime 的信号"""
        passed = []
        blocked = 0
        for sig in signals:
            if self.should_pass(sig, regime):
                passed.append(sig)
            else:
                blocked += 1
                logger.debug(
                    f"[RegimeGate] 拦截 {sig.strategy_name}/{sig.code}: "
                    f"regime={regime} 不在允许列表"
                )
        if blocked > 0:
            logger.info(
                f"[RegimeGate] regime={regime}, "
                f"放行 {len(passed)}/{len(signals)}, 拦截 {blocked}"
            )
        return passed
