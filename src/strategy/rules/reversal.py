"""反转策略

Tier 1 规则策略 — 买入近 N 日跌幅最大的股票 (均值回归)。
"""
from datetime import date
from typing import List, Dict, Any, Optional

from src.common.config import settings
from src.common.logger import get_logger
from src.strategy.base import BaseStrategy, Signal, HoldingPosition
from src.strategy.registry import register_strategy

logger = get_logger(__name__)


def _default_config():
    s = settings.strat_reversal
    return {
        "lookback_days": s.lookback_days,
        "top_n": s.top_n,
        "max_drawdown": s.max_drawdown,
    }


@register_strategy
class ReversalStrategy(BaseStrategy):
    """反转策略 — 抄底"""

    tier = "rule"
    name = "reversal"
    description = "反转: 买入近N日跌幅最大的股票, 博均值回归"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.cfg = {**_default_config(), **(config or {})}

    def generate_signals(
        self, trade_date: date, universe: List[str],
        holdings: Optional[List[HoldingPosition]] = None,
    ) -> List[Signal]:
        from src.data.qmt_client import QMTClient

        client = QMTClient()
        lookback = self.cfg["lookback_days"]
        data = client.get_market_data_ex(
            universe, period="1d", count=lookback + 5, dividend_type="front",
        )

        scored = []
        for code, df in data.items():
            if df is None or len(df) < lookback:
                continue
            recent = df.tail(lookback)
            if recent.iloc[0]["close"] <= 0:
                continue

            ret = (recent.iloc[-1]["close"] / recent.iloc[0]["close"] - 1) * 100

            if ret < self.cfg["max_drawdown"]:
                continue
            if ret >= 0:
                continue

            scored.append((code, ret))

        scored.sort(key=lambda x: x[1])
        top_n = self.cfg["top_n"]

        signals = []
        for rank, (code, ret) in enumerate(scored[:top_n], 1):
            signals.append(Signal(
                trade_date=trade_date,
                code=code,
                direction="buy",
                score=round(-ret, 4),
                strategy_name=self.name,
                strategy_tier=self.tier,
                reason=f"{lookback}日跌幅={ret:.2f}%",
                stop_loss_pct=self.cfg.get("stop_loss_pct", settings.strat_reversal.stop_loss_pct),
                take_profit_pct=self.cfg.get("take_profit_pct", settings.strat_reversal.take_profit_pct),
                max_hold_days=self.cfg.get("max_hold_days", settings.strat_reversal.max_hold_days),
                trailing_stop_pct=self.cfg.get("trailing_stop_pct", settings.strat_reversal.trailing_stop_pct),
                min_amount=self.cfg.get("min_amount", settings.signal_defaults.min_amount),
            ))

        if holdings:
            buy_codes = {s.code for s in signals}
            for pos in holdings:
                if pos.strategy_name != self.name or pos.code in buy_codes:
                    continue
                pnl = pos.profit_pct
                if pos.buy_price > 0 and pos.current_price > 0:
                    pnl = (pos.current_price / pos.buy_price - 1) * 100
                if pnl > self.cfg.get("bounce_target_pct", settings.strat_reversal.bounce_target_pct):
                    signals.append(Signal(
                        trade_date=trade_date,
                        code=pos.code,
                        direction="sell",
                        score=50,
                        strategy_name=self.name,
                        strategy_tier=self.tier,
                        reason=f"反弹目标达成 (盈利{pnl:.1f}%)",
                    ))

        logger.info(f"[{self.name}] {trade_date}: 信号 {len(signals)} 只")
        return signals
