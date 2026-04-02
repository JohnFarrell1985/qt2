"""风控模块

仓位限制、止损止盈、日内亏损限额。
"""
from typing import Dict, List, Optional

from src.common.logger import get_logger
from src.common.config import settings

logger = get_logger(__name__)


class RiskController:
    """风控控制器"""

    def __init__(
        self,
        stop_loss_pct: float = -8.0,
        take_profit_pct: float = 20.0,
        max_single_position_pct: float = 30.0,
        max_total_position_pct: float = 80.0,
        max_daily_loss_pct: float = -5.0,
    ):
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_single_position_pct = max_single_position_pct
        self.max_total_position_pct = max_total_position_pct
        self.max_daily_loss_pct = max_daily_loss_pct

    @classmethod
    def from_config(cls) -> "RiskController":
        risk = settings.trading.risk
        return cls(
            stop_loss_pct=risk.stop_loss_pct,
            take_profit_pct=risk.take_profit_pct,
            max_single_position_pct=risk.max_single_position_pct,
            max_total_position_pct=risk.max_total_position_pct,
            max_daily_loss_pct=risk.max_daily_loss_pct,
        )

    def check_position_limit(
        self, code: str, buy_amount: float, total_assets: float
    ) -> bool:
        """检查单股仓位限制"""
        pct = buy_amount / total_assets * 100 if total_assets > 0 else 100
        if pct > self.max_single_position_pct:
            logger.warning(
                f"[风控] {code} 仓位 {pct:.1f}% 超过限制 {self.max_single_position_pct}%"
            )
            return False
        return True

    def check_total_position(
        self, market_value: float, total_assets: float
    ) -> bool:
        """检查总仓位限制"""
        pct = market_value / total_assets * 100 if total_assets > 0 else 100
        if pct > self.max_total_position_pct:
            logger.warning(
                f"[风控] 总仓位 {pct:.1f}% 超过限制 {self.max_total_position_pct}%"
            )
            return False
        return True

    def check_stop_loss(
        self, code: str, current_price: float, cost_price: float
    ) -> bool:
        """止损检查。返回True表示需要止损"""
        if cost_price <= 0:
            return False
        pnl_pct = (current_price - cost_price) / cost_price * 100
        if pnl_pct <= self.stop_loss_pct:
            logger.warning(
                f"[风控] {code} 触发止损: 浮亏 {pnl_pct:.2f}% <= {self.stop_loss_pct}%"
            )
            return True
        return False

    def check_take_profit(
        self, code: str, current_price: float, cost_price: float
    ) -> bool:
        """止盈检查。返回True表示需要止盈"""
        if cost_price <= 0:
            return False
        pnl_pct = (current_price - cost_price) / cost_price * 100
        if pnl_pct >= self.take_profit_pct:
            logger.info(
                f"[风控] {code} 触发止盈: 浮盈 {pnl_pct:.2f}% >= {self.take_profit_pct}%"
            )
            return True
        return False

    def check_daily_loss(
        self, daily_pnl: float, total_assets: float
    ) -> bool:
        """日内亏损限额检查。返回True表示需要停止交易"""
        pct = daily_pnl / total_assets * 100 if total_assets > 0 else 0
        if pct <= self.max_daily_loss_pct:
            logger.warning(
                f"[风控] 日内亏损 {pct:.2f}% 触发限额 {self.max_daily_loss_pct}%，停止交易"
            )
            return True
        return False

    def calc_max_buy_amount(
        self, total_assets: float, current_market_value: float
    ) -> float:
        """计算最大可买入金额"""
        max_total = total_assets * self.max_total_position_pct / 100
        available = max_total - current_market_value
        max_single = total_assets * self.max_single_position_pct / 100
        return min(max(available, 0), max_single)
