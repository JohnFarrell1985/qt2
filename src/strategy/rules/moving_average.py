"""均线突破策略

Tier 1 规则策略 — 价格突破 N 日均线买入, 跌破卖出。
"""
from datetime import date
from typing import List, Dict, Any, Optional

import pandas as pd

from src.common.config import settings
from src.common.logger import get_logger
from src.strategy.base import BaseStrategy, Signal, HoldingPosition
from src.strategy.registry import register_strategy

logger = get_logger(__name__)


def _default_config():
    s = settings.strat_moving_average
    return {
        "short_ma": s.short_ma,
        "long_ma": s.long_ma,
        "top_n": s.top_n,
    }


@register_strategy
class MovingAverageStrategy(BaseStrategy):
    """双均线策略"""

    tier = "rule"
    name = "moving_average"
    description = "均线突破: 短均线上穿长均线买入, 下穿卖出"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.cfg = {**_default_config(), **(config or {})}

    def generate_signals(
        self, trade_date: date, universe: List[str],
        holdings: Optional[List[HoldingPosition]] = None,
    ) -> List[Signal]:
        from src.data.qmt_client import QMTClient

        client = QMTClient()
        long_ma = self.cfg["long_ma"]
        short_ma = self.cfg["short_ma"]
        count = long_ma + 5

        data = client.get_market_data_ex(
            universe, period="1d", count=count, dividend_type="front",
        )

        buy_candidates = []
        sell_candidates = []

        for code, df in data.items():
            if df is None or len(df) < long_ma + 1:
                continue
            closes = df["close"]
            ma_short = closes.rolling(short_ma).mean()
            ma_long = closes.rolling(long_ma).mean()

            if pd.isna(ma_short.iloc[-1]) or pd.isna(ma_long.iloc[-1]):
                continue

            prev_diff = ma_short.iloc[-2] - ma_long.iloc[-2]
            curr_diff = ma_short.iloc[-1] - ma_long.iloc[-1]
            strength = curr_diff / ma_long.iloc[-1] * 100 if ma_long.iloc[-1] > 0 else 0

            if prev_diff <= 0 < curr_diff:
                buy_candidates.append((code, strength))
            elif prev_diff >= 0 > curr_diff:
                sell_candidates.append((code, strength))

        buy_candidates.sort(key=lambda x: x[1], reverse=True)

        signals = []
        for code, strength in buy_candidates[: self.cfg["top_n"]]:
            signals.append(Signal(
                trade_date=trade_date,
                code=code,
                direction="buy",
                score=round(strength, 4),
                strategy_name=self.name,
                strategy_tier=self.tier,
                reason=f"MA{short_ma}上穿MA{long_ma} 强度={strength:.2f}%",
                stop_loss_pct=self.cfg.get("stop_loss_pct", settings.strat_moving_average.stop_loss_pct),
                take_profit_pct=self.cfg.get("take_profit_pct", settings.strat_moving_average.take_profit_pct),
                max_hold_days=self.cfg.get("max_hold_days", settings.strat_moving_average.max_hold_days),
                trailing_stop_pct=self.cfg.get("trailing_stop_pct", settings.strat_moving_average.trailing_stop_pct),
                min_amount=self.cfg.get("min_amount", settings.signal_defaults.min_amount),
            ))

        holding_codes = set()
        if holdings:
            holding_codes = {p.code for p in holdings if p.strategy_name == self.name}
        for code, strength in sell_candidates:
            if code not in holding_codes:
                continue
            signals.append(Signal(
                trade_date=trade_date,
                code=code,
                direction="sell",
                score=round(abs(strength), 4),
                strategy_name=self.name,
                strategy_tier=self.tier,
                reason=f"MA{short_ma}下穿MA{long_ma}",
            ))

        logger.info(f"[{self.name}] {trade_date}: 买 {len(buy_candidates)} 卖 {len(sell_candidates)}")
        return signals
