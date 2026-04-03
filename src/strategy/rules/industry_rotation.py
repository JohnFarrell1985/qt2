"""行业轮动策略

Tier 1 规则策略 — 按行业板块近期涨幅排名, 买入强势行业龙头。
"""
from datetime import date
from typing import List, Dict, Any, Optional

from src.common.config import settings
from src.common.logger import get_logger
from src.strategy.base import BaseStrategy, Signal, HoldingPosition
from src.strategy.registry import register_strategy

logger = get_logger(__name__)


def _default_config():
    s = settings.strat_industry_rotation
    return {
        "lookback_days": s.lookback_days,
        "top_industries": s.top_industries,
        "stocks_per_industry": s.stocks_per_industry,
    }


@register_strategy
class IndustryRotationStrategy(BaseStrategy):
    """行业轮动策略"""

    tier = "rule"
    name = "industry_rotation"
    description = "行业轮动: 选强势行业内涨幅最大的龙头股"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.cfg = {**_default_config(), **(config or {})}

    def generate_signals(
        self, trade_date: date, universe: List[str],
        holdings: Optional[List[HoldingPosition]] = None,
    ) -> List[Signal]:
        from src.data.qmt_client import QMTClient
        from src.common.db import get_session
        from src.data.models import Stock

        client = QMTClient()
        lookback = self.cfg["lookback_days"]

        with get_session() as session:
            stocks = session.query(Stock).filter(Stock.code.in_(universe)).all()
            code_industry = {s.code: s.industry or "未知" for s in stocks}

        data = client.get_market_data_ex(
            universe, period="1d", count=lookback + 5, dividend_type="front",
        )

        stock_returns: Dict[str, float] = {}
        for code, df in data.items():
            if df is None or len(df) < lookback:
                continue
            recent = df.tail(lookback)
            if recent.iloc[0]["close"] <= 0:
                continue
            ret = (recent.iloc[-1]["close"] / recent.iloc[0]["close"] - 1) * 100
            stock_returns[code] = ret

        industry_returns: Dict[str, List[float]] = {}
        industry_stocks: Dict[str, List] = {}
        for code, ret in stock_returns.items():
            ind = code_industry.get(code, "未知")
            industry_returns.setdefault(ind, []).append(ret)
            industry_stocks.setdefault(ind, []).append((code, ret))

        industry_avg = {
            ind: sum(rets) / len(rets)
            for ind, rets in industry_returns.items()
            if len(rets) >= 3
        }
        top_inds = sorted(industry_avg, key=industry_avg.get, reverse=True)[
            : self.cfg["top_industries"]
        ]

        signals = []
        for ind in top_inds:
            candidates = sorted(industry_stocks[ind], key=lambda x: x[1], reverse=True)
            for code, ret in candidates[: self.cfg["stocks_per_industry"]]:
                signals.append(Signal(
                    trade_date=trade_date,
                    code=code,
                    direction="buy",
                    score=round(ret, 4),
                    strategy_name=self.name,
                    strategy_tier=self.tier,
                    reason=f"行业={ind} 行业均涨={industry_avg[ind]:.1f}% 个股涨={ret:.1f}%",
                    stop_loss_pct=self.cfg.get("stop_loss_pct", settings.strat_industry_rotation.stop_loss_pct),
                    take_profit_pct=self.cfg.get("take_profit_pct", settings.strat_industry_rotation.take_profit_pct),
                    max_hold_days=self.cfg.get("max_hold_days", settings.strat_industry_rotation.max_hold_days),
                    trailing_stop_pct=self.cfg.get("trailing_stop_pct", settings.strat_industry_rotation.trailing_stop_pct),
                    min_amount=self.cfg.get("min_amount", settings.signal_defaults.min_amount),
                ))

        if holdings:
            buy_codes = {s.code for s in signals}
            top_ind_set = set(top_inds)
            for pos in holdings:
                if pos.strategy_name != self.name or pos.code in buy_codes:
                    continue
                ind = code_industry.get(pos.code, "未知")
                if ind not in top_ind_set:
                    signals.append(Signal(
                        trade_date=trade_date,
                        code=pos.code,
                        direction="sell",
                        score=50,
                        strategy_name=self.name,
                        strategy_tier=self.tier,
                        reason=f"行业走弱 (行业={ind})",
                    ))

        logger.info(f"[{self.name}] {trade_date}: 强势行业={top_inds}, 信号 {len(signals)} 只")
        return signals
