"""持仓监控器 — 扫描当前持仓, 触发卖出信号

五类卖出触发 (按优先级):
  1. 硬止损: 亏损 >= stop_loss_pct → 无条件卖出
  2. 移动止损: 从最高价回撤 >= trailing_stop_pct → 卖出锁定利润
  3. 止盈: 盈利 >= take_profit_pct → 分批/全部止盈
  4. 超期清仓: 持有天数 >= max_hold_days 且未盈利 → 卖出释放资金
  5. T+1 校验: 今日买入的不能生成卖出信号

参考:
  - A 股 T+1 散户实战: 次日开盘 30 分钟内完成止盈止损决策
  - 盈亏比 >= 1.5:1 + 胜率 > 50% = 长期盈利
  - 单票止损 -5% ~ -8%, 止盈 +10% ~ +20%
"""
from datetime import date
from typing import List, Dict, Any, Optional

from src.common.config import settings
from src.common.logger import get_logger
from src.strategy.base import Signal, HoldingPosition
from src.strategy.trading_rules import TRADING_RULES, infer_asset_type

logger = get_logger(__name__)


def _default_monitor_config() -> dict:
    s = settings.position_monitor
    return {
        "default_stop_loss_pct": s.default_stop_loss_pct,
        "default_take_profit_pct": s.default_take_profit_pct,
        "default_trailing_stop_pct": s.default_trailing_stop_pct,
        "default_max_hold_days": s.default_max_hold_days,
        "enable_trailing_stop": s.enable_trailing_stop,
        "partial_take_profit": s.partial_take_profit,
        "partial_take_profit_ratio": s.partial_take_profit_ratio,
        "force_sell_on_expiry": s.force_sell_on_expiry,
        "expiry_loss_threshold": s.expiry_loss_threshold,
    }


class PositionMonitor:
    """持仓监控器

    用法:
        monitor = PositionMonitor(config)
        sell_signals = monitor.scan(trade_date, holdings)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.cfg = {**_default_monitor_config(), **(config or {})}

    def scan(
        self,
        trade_date: date,
        holdings: List[HoldingPosition],
        signal_params: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> List[Signal]:
        """扫描全部持仓, 返回需要卖出的信号

        Args:
            trade_date: 当前交易日
            holdings: 当前持仓列表
            signal_params: 按 code 的个性化止损止盈参数
                {code: {"stop_loss_pct": -5, "take_profit_pct": 20, ...}}
        """
        if signal_params is None:
            signal_params = {}

        sell_signals: List[Signal] = []

        for pos in holdings:
            if not pos.can_sell:
                continue
            rule = TRADING_RULES[infer_asset_type(pos.code)]
            if rule.t_plus_n > 0 and pos.buy_date == trade_date:
                continue

            params = self._get_params(pos.code, signal_params)
            signal = self._check_position(trade_date, pos, params)
            if signal:
                sell_signals.append(signal)

        sell_signals.sort(key=lambda s: s.score, reverse=True)

        if sell_signals:
            logger.info(
                f"[持仓监控] {trade_date}: "
                f"扫描 {len(holdings)} 只持仓, "
                f"触发 {len(sell_signals)} 个卖出信号"
            )
        return sell_signals

    def _get_params(
        self, code: str, signal_params: Dict[str, Dict[str, float]]
    ) -> Dict[str, float]:
        base = {
            "stop_loss_pct": self.cfg["default_stop_loss_pct"],
            "take_profit_pct": self.cfg["default_take_profit_pct"],
            "trailing_stop_pct": self.cfg["default_trailing_stop_pct"],
            "max_hold_days": self.cfg["default_max_hold_days"],
        }
        if code in signal_params:
            base.update(signal_params[code])
        return base

    def _check_position(
        self,
        trade_date: date,
        pos: HoldingPosition,
        params: Dict[str, float],
    ) -> Optional[Signal]:
        """检查单个持仓, 返回卖出信号 (按优先级)"""

        profit_pct = pos.profit_pct
        if pos.buy_price > 0 and pos.current_price > 0:
            profit_pct = (pos.current_price / pos.buy_price - 1) * 100

        # 1. 硬止损
        stop_loss = params["stop_loss_pct"]
        if profit_pct <= stop_loss:
            return Signal(
                trade_date=trade_date,
                code=pos.code,
                direction="sell",
                score=100.0,
                quantity=pos.quantity,
                strategy_name="position_monitor",
                strategy_tier="risk",
                reason=f"止损触发: 亏损{profit_pct:.1f}% <= {stop_loss}%",
                stop_loss_pct=stop_loss,
            )

        # 2. 移动止损
        if self.cfg["enable_trailing_stop"] and pos.highest_price > 0:
            trailing_pct = params["trailing_stop_pct"]
            drawdown_from_high = (pos.current_price / pos.highest_price - 1) * 100
            if profit_pct > 0 and drawdown_from_high <= -trailing_pct:
                return Signal(
                    trade_date=trade_date,
                    code=pos.code,
                    direction="sell",
                    score=90.0,
                    quantity=pos.quantity,
                    strategy_name="position_monitor",
                    strategy_tier="risk",
                    reason=(
                        f"移动止损: 从最高点回撤{drawdown_from_high:.1f}% "
                        f"(最高{pos.highest_price:.2f} 现{pos.current_price:.2f})"
                    ),
                    trailing_stop_pct=trailing_pct,
                )

        # 3. 止盈
        take_profit = params["take_profit_pct"]
        if profit_pct >= take_profit:
            sell_qty = pos.quantity
            if self.cfg["partial_take_profit"]:
                sell_qty = max(100, int(pos.quantity * self.cfg["partial_take_profit_ratio"] / 100) * 100)

            return Signal(
                trade_date=trade_date,
                code=pos.code,
                direction="sell",
                score=80.0,
                quantity=sell_qty,
                strategy_name="position_monitor",
                strategy_tier="risk",
                reason=f"止盈触发: 盈利{profit_pct:.1f}% >= {take_profit}%",
                take_profit_pct=take_profit,
            )

        # 4. 超期清仓
        max_days = int(params["max_hold_days"])
        if self.cfg["force_sell_on_expiry"] and pos.hold_days >= max_days:
            threshold = self.cfg.get("expiry_loss_threshold", 0.0)
            if profit_pct <= threshold:
                return Signal(
                    trade_date=trade_date,
                    code=pos.code,
                    direction="sell",
                    score=60.0,
                    quantity=pos.quantity,
                    strategy_name="position_monitor",
                    strategy_tier="risk",
                    reason=(
                        f"超期清仓: 持有{pos.hold_days}天>={max_days}天, "
                        f"盈利{profit_pct:.1f}%未达标"
                    ),
                    max_hold_days=max_days,
                )

        return None
