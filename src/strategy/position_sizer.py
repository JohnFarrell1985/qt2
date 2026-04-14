"""仓位分配器

三种分配模式:
  - equal:     等权分配 (最简单, 散户推荐)
  - atr:       按 ATR 波动率反比分配 (波动大的仓位小)
  - kelly:     简化凯利公式 (按胜率和盈亏比分配)

约束:
  - 单票仓位不超过 max_single_pct
  - 总仓位不超过 max_total_pct × position_multiplier (宏观调节)
  - 最小交易单位 100 股 (A 股)
  - 买入金额向下取整到 100 股的倍数

参考实战经验:
  - 散户单票 10%~20%, 分仓 3~5 只
  - 震荡市总仓位 60%~80%, 熊市 30%~50%
"""
from typing import List, Dict, Any, Optional

from src.common.config import settings
from src.common.logger import get_logger
from src.strategy.base import ActionItem
from src.strategy.trading_rules import get_trading_rule

logger = get_logger(__name__)


def _default_sizer_config() -> dict:
    s = settings.sizer
    return {
        "mode": s.mode,
        "max_single_pct": s.max_single_pct,
        "max_total_pct": s.max_total_pct,
        "position_multiplier": 1.0,
        "min_trade_amount": s.min_trade_amount,
        "lot_size": s.lot_size,
        "kelly_fraction": s.kelly_fraction,
        "drawdown_guard_enabled": s.drawdown_guard_enabled,
    }


class DrawdownGuard:
    """回撤自适应仓位缩减"""

    DEFAULT_THRESHOLDS = [
        (-0.03, 0.90),
        (-0.05, 0.75),
        (-0.08, 0.50),
        (-0.12, 0.25),
        (-0.15, 0.10),
    ]

    def __init__(self, thresholds: Optional[List[tuple]] = None):
        self.thresholds = sorted(
            thresholds or self.DEFAULT_THRESHOLDS, key=lambda x: x[0],
        )

    def scale_factor(self, current_drawdown: float) -> float:
        """根据当前回撤幅度返回仓位缩放因子 (0~1)

        thresholds 按 drawdown 升序排列 (最负在前),
        匹配第一个 <= current_drawdown 的阈值。
        """
        for threshold, scale in self.thresholds:
            if current_drawdown <= threshold:
                return scale
        return 1.0


class PositionSizer:
    """仓位分配器"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.cfg = {**_default_sizer_config(), **(config or {})}
        self._drawdown_guard = DrawdownGuard() if self.cfg.get("drawdown_guard_enabled") else None

    def allocate(
        self,
        buy_actions: List[ActionItem],
        total_capital: float,
        available_cash: float,
        current_position_pct: float = 0.0,
        atr_map: Optional[Dict[str, float]] = None,
        price_map: Optional[Dict[str, float]] = None,
        current_drawdown: float = 0.0,
    ) -> List[ActionItem]:
        """为买入操作分配仓位

        Args:
            buy_actions: 买入操作列表 (已排好优先级)
            total_capital: 总资产
            available_cash: 可用现金
            current_position_pct: 当前持仓占比 (0~100)
            atr_map: {code: atr_value} ATR 模式使用
            price_map: {code: current_price} 计算数量用
            current_drawdown: 当前回撤幅度 (负数, 如 -0.05 表示 5% 回撤)
        """
        if not buy_actions:
            return []
        if price_map is None:
            price_map = {}

        multiplier = self.cfg["position_multiplier"]
        max_total = self.cfg["max_total_pct"] * multiplier
        max_single = self.cfg["max_single_pct"]
        remaining_pct = max(0, max_total - current_position_pct)

        if self._drawdown_guard and current_drawdown < 0:
            factor = self._drawdown_guard.scale_factor(current_drawdown)
            remaining_pct *= factor
            logger.info(
                f"[仓位] DrawdownGuard: 回撤 {current_drawdown:.2%}, "
                f"缩放因子 {factor:.2f}, 可用仓位 {remaining_pct:.1f}%"
            )

        mode = self.cfg["mode"]
        if mode == "atr" and atr_map:
            weights = self._calc_atr_weights(buy_actions, atr_map)
        elif mode == "kelly":
            weights = self._calc_kelly_weights(buy_actions)
        else:
            weights = self._calc_equal_weights(buy_actions)

        remaining_cash = min(available_cash, total_capital * remaining_pct / 100)
        default_lot = self.cfg["lot_size"]
        min_amt = self.cfg["min_trade_amount"]

        allocated = []
        for action, w in zip(buy_actions, weights):
            code = action.code
            target_pct = min(w * remaining_pct, max_single)
            target_amount = total_capital * target_pct / 100
            target_amount = min(target_amount, remaining_cash)

            if target_amount < min_amt:
                logger.debug(f"[仓位] {code} 分配金额 {target_amount:.0f} < 最低 {min_amt}, 跳过")
                continue

            lot = get_trading_rule(code).min_lot_size if code else default_lot

            price = price_map.get(code, 0)
            if price > 0:
                qty = int(target_amount / price / lot) * lot
                if qty < lot:
                    continue
                actual_amount = qty * price
            else:
                qty = 0
                actual_amount = target_amount

            action.target_quantity = qty
            action.target_amount = actual_amount
            action.target_weight_pct = round(target_pct, 2)
            remaining_cash -= actual_amount

            allocated.append(action)
            logger.debug(
                f"[仓位] {code}: {target_pct:.1f}% = {actual_amount:.0f}元 "
                f"({qty}股 @ {price:.2f})"
            )

            if remaining_cash < min_amt:
                break

        logger.info(
            f"[仓位] 分配 {len(allocated)}/{len(buy_actions)} 只, "
            f"mode={mode}, 剩余现金 {remaining_cash:.0f}"
        )
        return allocated

    def _calc_equal_weights(self, actions: List[ActionItem]) -> List[float]:
        n = len(actions)
        return [1.0 / n] * n

    def _calc_atr_weights(
        self, actions: List[ActionItem], atr_map: Dict[str, float]
    ) -> List[float]:
        """ATR 反比加权: 波动率高的仓位小"""
        atrs = []
        for a in actions:
            atr = atr_map.get(a.code, 1.0)
            atrs.append(max(atr, 0.001))

        inv_atrs = [1.0 / a for a in atrs]
        total = sum(inv_atrs)
        if total == 0:
            return self._calc_equal_weights(actions)
        return [w / total for w in inv_atrs]

    def _calc_kelly_weights(self, actions: List[ActionItem]) -> List[float]:
        """Fractional Kelly: f = kelly_fraction * (bp - q) / b

        b = 盈亏比 (take_profit / |stop_loss|)
        p = 估计胜率 (暂用 0.55)
        q = 1 - p
        kelly_fraction 来自配置, 默认 0.25 (四分之一 Kelly)
        """
        fraction = self.cfg.get("kelly_fraction", 0.25)
        weights = []
        for a in actions:
            if a.signals:
                tp = abs(a.signals[0].take_profit_pct)
                sl = abs(a.signals[0].stop_loss_pct)
            else:
                tp, sl = 15.0, 8.0

            b = tp / sl if sl > 0 else 2.0
            p = 0.55
            q = 1 - p
            full_kelly = (b * p - q) / b
            kelly = max(0, full_kelly) * fraction
            weights.append(kelly)

        total = sum(weights)
        if total == 0:
            return self._calc_equal_weights(actions)
        return [w / total for w in weights]
