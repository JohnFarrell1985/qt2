"""低波红利策略

Tier 1 规则策略 — 选波动率低 + 股息率高的股票, 防守型。
适合熊市/震荡市。
"""
from datetime import date
from typing import List, Dict, Any, Optional

import numpy as np

from src.common.config import settings
from src.common.logger import get_logger
from src.strategy.base import BaseStrategy, Signal, HoldingPosition
from src.strategy.registry import register_strategy

logger = get_logger(__name__)


def _default_config():
    s = settings.strat_low_vol_dividend
    return {
        "lookback_days": s.lookback_days,
        "vol_weight": s.vol_weight,
        "div_weight": s.div_weight,
        "max_vol_pct": s.max_vol_pct,
        "min_dividend_yield": s.min_dividend_yield,
        "top_n": s.top_n,
    }


@register_strategy
class LowVolDividendStrategy(BaseStrategy):
    """低波红利策略"""

    tier = "rule"
    name = "low_vol_dividend"
    description = "低波红利: 选低波动+高股息股票, 防御型"

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

        # 获取行情计算波动率
        data = client.get_market_data_ex(
            universe, period="1d", count=lookback + 5, dividend_type="front",
        )

        # 获取股息率 (从 DB stocks 表的基础信息, 可扩展为实时)
        with get_session() as session:
            stocks = session.query(Stock).filter(Stock.code.in_(universe)).all()
            code_info = {s.code: s for s in stocks}

        scored = []
        for code, df in data.items():
            if df is None or len(df) < lookback:
                continue
            recent = df.tail(lookback)
            closes = recent["close"]
            if closes.iloc[0] <= 0:
                continue

            returns = closes.pct_change().dropna()
            if len(returns) < 10:
                continue

            vol = float(np.std(returns) * np.sqrt(252) * 100)
            if vol > self.cfg["max_vol_pct"]:
                continue

            stock_info = code_info.get(code)
            div_yield = 0.0
            if stock_info:
                if hasattr(stock_info, "dividend_yield") and stock_info.dividend_yield:
                    div_yield = float(stock_info.dividend_yield)
                elif stock_info.pe_ttm and stock_info.pe_ttm > 0:
                    div_yield = 100.0 / stock_info.pe_ttm * 0.3

            if div_yield < self.cfg["min_dividend_yield"]:
                continue

            vol_norm = vol / self.cfg["max_vol_pct"]
            div_norm = min(div_yield / 10.0, 1.0)
            score = (
                (1.0 - vol_norm) * self.cfg["vol_weight"]
                + div_norm * self.cfg["div_weight"]
            )
            scored.append((code, score, vol, div_yield))

        scored.sort(key=lambda x: x[1], reverse=True)
        top_n = self.cfg["top_n"]

        signals = []
        for code, score, vol, div_y in scored[:top_n]:
            signals.append(Signal(
                trade_date=trade_date,
                code=code,
                direction="buy",
                score=round(score, 4),
                strategy_name=self.name,
                strategy_tier=self.tier,
                reason=f"波动率={vol:.1f}% 股息率≈{div_y:.1f}%",
                stop_loss_pct=self.cfg.get("stop_loss_pct", settings.strat_low_vol_dividend.stop_loss_pct),
                take_profit_pct=self.cfg.get("take_profit_pct", settings.strat_low_vol_dividend.take_profit_pct),
                max_hold_days=self.cfg.get("max_hold_days", settings.strat_low_vol_dividend.max_hold_days),
                trailing_stop_pct=self.cfg.get("trailing_stop_pct", settings.strat_low_vol_dividend.trailing_stop_pct),
                min_amount=self.cfg.get("min_amount", settings.signal_defaults.min_amount),
            ))

        if holdings:
            buy_codes = {s.code for s in signals}
            max_vol = self.cfg["max_vol_pct"]
            held_codes = [
                pos.code for pos in holdings
                if pos.strategy_name == self.name and pos.code not in buy_codes
            ]
            if held_codes:
                held_data = client.get_market_data_ex(
                    held_codes, period="1d", count=lookback + 5, dividend_type="front",
                )
                for pos in holdings:
                    if pos.strategy_name != self.name or pos.code in buy_codes:
                        continue
                    df = held_data.get(pos.code)
                    if df is None or len(df) < lookback:
                        continue
                    recent = df.tail(lookback)
                    closes = recent["close"]
                    if closes.iloc[0] <= 0:
                        continue
                    rets = closes.pct_change().dropna()
                    if len(rets) < 10:
                        continue
                    vol = float(np.std(rets) * np.sqrt(252) * 100)
                    if vol > max_vol:
                        signals.append(Signal(
                            trade_date=trade_date,
                            code=pos.code,
                            direction="sell",
                            score=50,
                            strategy_name=self.name,
                            strategy_tier=self.tier,
                            reason=f"波动率飙升 (vol={vol:.1f}% > {max_vol:.0f}%)",
                        ))

        logger.info(f"[{self.name}] {trade_date}: 信号 {len(signals)} 只")
        return signals
