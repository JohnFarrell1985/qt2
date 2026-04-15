"""动量策略

Tier 1 规则策略 — 买入近 N 日涨幅最大的股票 (趋势追随)。
"""
from datetime import date
from typing import List, Dict, Any, Optional

from src.common.config import settings
from src.common.logger import get_logger
from src.strategy.base import BaseStrategy, Signal, HoldingPosition
from src.strategy.registry import register_strategy

logger = get_logger(__name__)


def _default_config():
    s = settings.strat_momentum
    return {
        "lookback_days": s.lookback_days,
        "top_n": s.top_n,
        "min_turnover": s.min_turnover,
    }


@register_strategy
class MomentumStrategy(BaseStrategy):
    """动量策略 — 追涨"""

    tier = "rule"
    name = "momentum"
    description = "动量: 买入近N日涨幅最大的股票"

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
        count = lookback + 5

        data = client.get_market_data_ex(
            universe, period="1d", count=count, dividend_type="front",
        )

        scored = []
        for code, df in data.items():
            if df is None or len(df) < lookback:
                continue
            recent = df.tail(lookback)
            if hasattr(recent.index, 'is_monotonic_increasing'):
                assert recent.index.is_monotonic_increasing, (
                    f"{code}: 行情数据未按时间升序排列, iloc[0]={recent.index[0]}, iloc[-1]={recent.index[-1]}"
                )
            if recent.iloc[0]["close"] <= 0:
                continue

            ret = (recent.iloc[-1]["close"] / recent.iloc[0]["close"] - 1) * 100
            avg_turnover = recent["turnoverRate"].mean() if "turnoverRate" in recent.columns else 1.0

            if avg_turnover < self.cfg["min_turnover"]:
                continue

            scored.append((code, ret))

        scored.sort(key=lambda x: x[1], reverse=True)
        top_n = self.cfg["top_n"]

        signals = []
        for rank, (code, ret) in enumerate(scored[:top_n], 1):
            signals.append(Signal(
                trade_date=trade_date,
                code=code,
                direction="buy",
                score=round(ret, 4),
                strategy_name=self.name,
                strategy_tier=self.tier,
                reason=f"{lookback}日涨幅={ret:.2f}%",
                stop_loss_pct=self.cfg.get("stop_loss_pct", settings.strat_momentum.stop_loss_pct),
                take_profit_pct=self.cfg.get("take_profit_pct", settings.strat_momentum.take_profit_pct),
                max_hold_days=self.cfg.get("max_hold_days", settings.strat_momentum.max_hold_days),
                trailing_stop_pct=self.cfg.get("trailing_stop_pct", settings.strat_momentum.trailing_stop_pct),
                min_amount=self.cfg.get("min_amount", settings.signal_defaults.min_amount),
            ))

        if holdings:
            buy_codes = {s.code for s in signals}
            held_returns = {code: ret for code, ret in scored}
            for pos in holdings:
                if pos.strategy_name != self.name or pos.code in buy_codes:
                    continue
                ret = held_returns.get(pos.code)
                if ret is not None and ret < 0:
                    signals.append(Signal(
                        trade_date=trade_date,
                        code=pos.code,
                        direction="sell",
                        score=50,
                        strategy_name=self.name,
                        strategy_tier=self.tier,
                        reason="动量反转",
                    ))

        logger.info(f"[{self.name}] {trade_date}: 信号 {len(signals)} 只")
        return signals
