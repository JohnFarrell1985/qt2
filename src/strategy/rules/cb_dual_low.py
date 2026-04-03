"""双低可转债策略

Tier 1 规则策略 — 双低 = 转债价格 + 转股溢价率 的加权得分。
转债价格越低、转股溢价率越低, 安全边际越高。
"""
from datetime import date
from typing import List, Dict, Any, Optional

from src.common.config import settings
from src.common.logger import get_logger
from src.strategy.base import BaseStrategy, Signal, HoldingPosition
from src.strategy.registry import register_strategy

logger = get_logger(__name__)


def _default_config():
    s = settings.strat_cb_dual_low
    return {
        "price_weight": s.price_weight,
        "premium_weight": s.premium_weight,
        "max_price": s.max_price,
        "max_premium": s.max_premium,
        "min_rating": s.min_rating,
        "top_n": s.top_n,
    }

RATING_ORDER = ["AAA", "AA+", "AA", "AA-", "A+", "A", "A-", "BBB+", "BBB", "BBB-"]


def _rating_pass(level: str, min_rating: str) -> bool:
    if not level or not min_rating:
        return True
    try:
        return RATING_ORDER.index(level) <= RATING_ORDER.index(min_rating)
    except ValueError:
        return True


@register_strategy
class CBDualLowStrategy(BaseStrategy):
    """双低可转债策略"""

    tier = "rule"
    name = "cb_dual_low"
    description = "双低可转债: 价格+溢价率加权排序, 选最低分转债"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.cfg = {**_default_config(), **(config or {})}

    def generate_signals(
        self, trade_date: date, universe: List[str],
        holdings: Optional[List[HoldingPosition]] = None,
    ) -> List[Signal]:
        from src.data.qmt_client import QMTClient

        client = QMTClient()
        scored = []
        dual_low_map: Dict[str, float] = {}

        for code in universe:
            try:
                info = client.get_cb_info(code)
                if not info:
                    continue

                price_data = client.get_market_data_ex([code], period="1d", count=1)
                df = price_data.get(code)
                if df is None or df.empty:
                    continue

                close_price = float(df.iloc[-1]["close"])
                premium = float(info.get("analConvpremiumratio", 999))
                level = str(info.get("level", ""))

                dual_low = (
                    close_price * self.cfg["price_weight"]
                    + premium * self.cfg["premium_weight"]
                )
                dual_low_map[code] = dual_low

                if close_price > self.cfg["max_price"]:
                    continue
                if premium > self.cfg["max_premium"]:
                    continue
                if not _rating_pass(level, self.cfg["min_rating"]):
                    continue

                scored.append((code, dual_low, close_price, premium, level))
            except Exception as e:
                logger.debug(f"双低策略跳过 {code}: {e}")

        scored.sort(key=lambda x: x[1])
        top_n = self.cfg["top_n"]

        signals = []
        for rank, (code, score, price, prem, lvl) in enumerate(scored[:top_n], 1):
            signals.append(Signal(
                trade_date=trade_date,
                code=code,
                direction="buy",
                score=round(-score, 4),
                strategy_name=self.name,
                strategy_tier=self.tier,
                reason=f"双低={score:.1f} 价格={price:.2f} 溢价率={prem:.1f}% 评级={lvl}",
                stop_loss_pct=self.cfg.get("stop_loss_pct", settings.strat_cb_dual_low.stop_loss_pct),
                take_profit_pct=self.cfg.get("take_profit_pct", settings.strat_cb_dual_low.take_profit_pct),
                max_hold_days=self.cfg.get("max_hold_days", settings.strat_cb_dual_low.max_hold_days),
                min_amount=self.cfg.get("min_amount", settings.strat_cb_dual_low.min_amount),
            ))

        buy_codes = {s.code for s in signals}

        if holdings:
            max_price = self.cfg["max_price"]
            max_premium = self.cfg["max_premium"]
            sell_threshold = max_price * self.cfg["price_weight"] + max_premium * self.cfg["premium_weight"]
            for pos in holdings:
                if pos.strategy_name != self.name or not pos.can_sell:
                    continue
                if pos.code in buy_codes:
                    continue
                dl = dual_low_map.get(pos.code)
                if dl is not None and dl > sell_threshold:
                    signals.append(Signal(
                        trade_date=trade_date,
                        code=pos.code,
                        direction="sell",
                        score=round(dl, 4),
                        strategy_name=self.name,
                        strategy_tier=self.tier,
                        reason=f"双低值升高 (双低={dl:.1f} > 阈值{sell_threshold:.1f})",
                    ))

        logger.info(f"[{self.name}] {trade_date}: 筛选 {len(scored)} 只, 信号 {len(signals)} 只")
        return signals
