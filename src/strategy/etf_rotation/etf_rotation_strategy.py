"""ETF 全球资产轮动策略 — 月度调仓主策略类"""
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from src.common.config import settings
from src.common.logger import get_logger
from src.strategy.base import BaseStrategy, HoldingPosition, Signal
from src.strategy.etf_rotation.crash_guard import CrashGuard
from src.strategy.etf_rotation.momentum import score as momentum_score
from src.strategy.etf_rotation.rotator import ETFRotator
from src.strategy.etf_rotation.universe import ETFUniverse
from src.strategy.registry import register_strategy

logger = get_logger(__name__)

PRICE_HISTORY_MONTHS = 13
TRADING_DAYS_PER_MONTH = 21


@register_strategy
class ETFRotationStrategy(BaseStrategy):
    """ETF 全球资产轮动策略 — 月度调仓

    流程:
    1. 加载 ETF 价格矩阵
    2. 计算动量因子
    3. 崩盘护卫检测
    4. 判断是否调仓日
    5. 排名选择 → 防锯齿 → 止损
    6. 生成买卖信号
    """

    tier = "rule"
    name = "etf_rotation"
    description = "ETF 全球资产轮动策略 — 月度调仓"

    def __init__(self, config: Optional[dict] = None):
        super().__init__(config)
        self._cfg = settings.etf_rotation
        self._universe = ETFUniverse()
        self._rotator = ETFRotator()
        self._crash_guard = CrashGuard(
            enable_breadth=True,
            enable_absolute=True,
            enable_volatility=self._cfg.volatility_gate,
        )
        self._last_rebalance_date: Optional[date] = self.config.get("last_rebalance_date")

    def generate_signals(
        self,
        trade_date: date,
        universe: list[str],
        holdings: Optional[list[HoldingPosition]] = None,
    ) -> list[Signal]:
        """主入口 — 生成 ETF 轮动交易信号"""

        if not self._cfg.enabled:
            logger.debug("ETF 轮动策略已禁用")
            return []

        prices = self._load_prices(trade_date)
        if prices.empty:
            logger.warning("ETF 轮动: 无法加载价格数据, 跳过 trade_date=%s", trade_date)
            return []

        stop_loss_sells = self._check_stop_loss(holdings, prices)

        is_rebal = self._rotator.is_rebalance_day(
            self._last_rebalance_date, trade_date, self._cfg.rebalance_interval,
        )

        if not is_rebal and not stop_loss_sells:
            logger.debug("ETF 轮动: 非调仓日且无止损, 跳过")
            return []

        scores = momentum_score(
            prices, method=self._cfg.momentum_method, lookback_days=self._cfg.lookback_days,
        )

        cash_fraction = self._evaluate_crash_guard(prices)

        signals: list[Signal] = []

        for code in stop_loss_sells:
            signals.append(self._make_signal(
                trade_date, code, "sell", score=0.0,
                reason=f"止损卖出 ({self.name})",
            ))

        if not is_rebal:
            return signals

        risk_scores = scores.reindex(self._universe.risk_pool).dropna()
        selected = self._rotator.rank_and_select(
            risk_scores, top_k=self._cfg.top_k,
            score_min=self._cfg.score_min, score_max=self._cfg.score_max,
        )

        selected = self._rotator.anti_whipsaw_filter(
            selected, holdings, risk_scores,
            min_hold_days=self._cfg.min_hold_days,
            rank_threshold=self._cfg.rank_threshold,
        )

        if cash_fraction >= 1.0:
            selected = []

        holding_codes = {h.code for h in holdings} if holdings else set()

        for code in holding_codes:
            if code not in selected and code not in [s.code for s in signals]:
                signals.append(self._make_signal(
                    trade_date, code, "sell",
                    score=float(scores.get(code, 0.0)),
                    reason=f"轮动卖出 — 排名不足 top_{self._cfg.top_k}",
                ))

        weight_per_etf = self._calc_weight(len(selected), cash_fraction)

        for code in selected:
            if code not in holding_codes:
                s = float(risk_scores.get(code, 0.0))
                signals.append(self._make_signal(
                    trade_date, code, "buy", score=s,
                    reason=f"轮动买入 — {self._cfg.momentum_method} 排名 top_{self._cfg.top_k}",
                    target_weight_pct=weight_per_etf,
                ))

        if cash_fraction > 0 and cash_fraction < 1.0:
            for code in self._universe.defensive_pool:
                if code not in holding_codes and code not in [s.code for s in signals]:
                    signals.append(self._make_signal(
                        trade_date, code, "buy", score=0.1,
                        reason=f"防御配置 — cash_fraction={cash_fraction:.0%}",
                        target_weight_pct=cash_fraction * 100 / max(len(self._universe.defensive_pool), 1),
                    ))

        self._last_rebalance_date = trade_date
        logger.info("ETF 轮动 %s: %d 信号, cash=%.0f%%, selected=%s",
                     trade_date, len(signals), cash_fraction * 100, selected)
        return signals

    # ------ private helpers ------

    def _load_prices(self, trade_date: date) -> pd.DataFrame:
        all_codes = self._universe.get_all_codes()
        if not all_codes:
            return pd.DataFrame()

        start = trade_date - timedelta(days=int(PRICE_HISTORY_MONTHS * 30 * 1.5))
        return self._universe.load_prices(all_codes, start, trade_date)

    def _evaluate_crash_guard(self, prices: pd.DataFrame) -> float:
        canary_cols = [c for c in self._universe.canary_pool if c in prices.columns]
        risk_cols = [c for c in self._universe.risk_pool if c in prices.columns]

        canary_prices = prices[canary_cols] if canary_cols else pd.DataFrame()
        risk_prices = prices[risk_cols] if risk_cols else pd.DataFrame()

        return self._crash_guard.evaluate(canary_prices, risk_prices, prices)

    def _check_stop_loss(
        self, holdings: Optional[list[HoldingPosition]], prices: pd.DataFrame,
    ) -> list[str]:
        if not holdings:
            return []
        return self._rotator.check_stop_loss(
            holdings,
            stop_loss_daily=self._cfg.stop_loss_daily,
            stop_loss_3d=self._cfg.stop_loss_3d,
            prices=prices if not prices.empty else None,
        )

    def _calc_weight(self, n_selected: int, cash_fraction: float) -> float:
        if n_selected == 0:
            return 0.0
        equity_fraction = 1.0 - cash_fraction
        return equity_fraction * 100.0 / n_selected

    def _make_signal(
        self, trade_date: date, code: str, direction: str,
        score: float = 0.0, reason: str = "",
        target_weight_pct: float = 0.0,
    ) -> Signal:
        return Signal(
            trade_date=trade_date,
            code=code,
            direction=direction,
            score=score,
            strategy_name=self.name,
            strategy_tier=self.tier,
            reason=reason,
            stop_loss_pct=-self._cfg.stop_loss_daily * 100,
            take_profit_pct=15.0,
            max_hold_days=self._cfg.rebalance_interval,
            target_weight_pct=target_weight_pct,
        )
