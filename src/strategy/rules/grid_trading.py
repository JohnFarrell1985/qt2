"""T+1 宽网格交易策略

Tier 1 规则策略 — 适配 A 股 T+1 规则的网格策略。

T+1 核心逻辑:
    买卖发生在不同交易日。今天扫描标的池, 对价格接近网格下沿的标的
    生成买入信号; 对已持仓且价格接近网格上沿的标的生成卖出信号 (隔日
    卖出, 即 T+1 日才能执行)。不会对同一标的在同一天同时产生买+卖,
    避免了日内回转限制。
"""
from datetime import date
from typing import List, Dict, Any, Optional

from src.common.config import settings
from src.common.logger import get_logger
from src.strategy.base import BaseStrategy, Signal, HoldingPosition
from src.strategy.registry import register_strategy

logger = get_logger(__name__)


def _default_config():
    s = settings.strat_grid_trading
    return {
        "grid_pct": s.grid_pct,
        "lookback_days": s.lookback_days,
        "top_n": s.top_n,
    }


@register_strategy
class GridTradingStrategy(BaseStrategy):
    """T+1 宽网格交易策略"""

    tier = "rule"
    name = "grid_trading"
    description = "T+1宽网格: 接近下沿买入, 持仓接近上沿隔日卖出"

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
        grid_pct = self.cfg["grid_pct"] / 100.0

        held_codes = set()
        if holdings:
            held_codes = {
                pos.code for pos in holdings
                if pos.strategy_name == self.name
            }

        all_codes = list(set(universe) | held_codes)

        data = client.get_market_data_ex(
            all_codes, period="1d", count=lookback + 5, dividend_type="front",
        )

        grid_info: Dict[str, tuple] = {}
        for code, df in data.items():
            if df is None or len(df) < lookback:
                continue
            recent = df.tail(lookback)
            high = recent["high"].max()
            low = recent["low"].min()
            if high <= low or low <= 0:
                continue
            price = float(recent.iloc[-1]["close"])
            grid_info[code] = (price, low, high)

        buy_scored = []
        for code in universe:
            if code in held_codes:
                continue
            info = grid_info.get(code)
            if info is None:
                continue
            price, low, high = info
            grid_size = (high - low) * grid_pct
            dist_to_low = price - low
            if dist_to_low < grid_size:
                score = 1.0 - dist_to_low / grid_size
                buy_scored.append((code, score, price, low, high))

        buy_scored.sort(key=lambda x: x[1], reverse=True)

        signals = []
        for code, score, price, low, high in buy_scored[: self.cfg["top_n"]]:
            signals.append(Signal(
                trade_date=trade_date,
                code=code,
                direction="buy",
                score=round(score, 4),
                strategy_name=self.name,
                strategy_tier=self.tier,
                reason=f"网格下沿买入 价格={price:.2f} 区间=[{low:.2f},{high:.2f}]",
                stop_loss_pct=self.cfg.get("stop_loss_pct", settings.strat_grid_trading.stop_loss_pct),
                take_profit_pct=self.cfg.get("take_profit_pct", settings.strat_grid_trading.take_profit_pct),
                max_hold_days=self.cfg.get("max_hold_days", settings.strat_grid_trading.max_hold_days),
            ))

        sell_count = 0
        if holdings:
            for pos in holdings:
                if pos.strategy_name != self.name or not pos.can_sell:
                    continue
                info = grid_info.get(pos.code)
                if info is None:
                    continue
                price, low, high = info
                grid_size = (high - low) * grid_pct
                dist_to_high = high - price
                if dist_to_high < grid_size:
                    score = 1.0 - dist_to_high / grid_size
                    signals.append(Signal(
                        trade_date=trade_date,
                        code=pos.code,
                        direction="sell",
                        score=round(score, 4),
                        strategy_name=self.name,
                        strategy_tier=self.tier,
                        reason=f"网格上沿 隔日卖出 价格={price:.2f} 区间=[{low:.2f},{high:.2f}]",
                    ))
                    sell_count += 1

        logger.info(f"[{self.name}] {trade_date}: 买 {len(buy_scored)} 卖 {sell_count}")
        return signals
