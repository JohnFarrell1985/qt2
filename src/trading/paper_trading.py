"""模拟盘交易引擎

连接QMT模拟盘账户，根据ML策略自动执行交易。
"""
from typing import List, Dict, Optional

from src.common.logger import get_logger
from src.trading.qmt_trader import QMTTrader
from src.trading.order_manager import OrderManager
from src.trading.position_manager import PositionManager
from src.trading.risk_control import RiskController

logger = get_logger(__name__)


class PaperTradingEngine:
    """模拟盘交易引擎"""

    def __init__(
        self,
        trader: Optional[QMTTrader] = None,
        risk_controller: Optional[RiskController] = None,
    ):
        self.trader = trader or QMTTrader()
        self.risk = risk_controller or RiskController.from_config()
        self.order_mgr = OrderManager(self.trader, account_type="paper")
        self.position_mgr = PositionManager(self.trader, account_type="paper")

    def connect(self) -> bool:
        """连接交易服务"""
        return self.trader.connect()

    def execute_signals(self, signals: List[Dict]) -> List[Dict]:
        """执行交易信号

        Args:
            signals: [{"code": "600519.SH", "signal": "buy", "rank": 1}, ...]

        Returns:
            执行结果列表
        """
        asset = self.trader.query_asset()
        total_assets = asset.get("total_asset", 0)
        cash = asset.get("cash", 0)
        market_value = asset.get("market_value", 0)
        results = []

        current_positions = {
            p["code"]: p for p in self.position_mgr.get_current_positions()
        }

        for sig in signals:
            code = sig["code"]
            signal = sig["signal"]

            if signal == "buy":
                if code in current_positions:
                    results.append({"code": code, "action": "skip", "reason": "already_held"})
                    continue

                max_amount = self.risk.calc_max_buy_amount(total_assets, market_value)
                if max_amount < 1000:
                    results.append({"code": code, "action": "skip", "reason": "insufficient_quota"})
                    continue

                buy_amount = min(max_amount, cash * 0.9)
                quantity = int(buy_amount / 100) * 100

                if quantity <= 0:
                    results.append({"code": code, "action": "skip", "reason": "quantity_zero"})
                    continue

                order_id = self.order_mgr.submit_order(
                    code=code, direction="buy", quantity=quantity
                )
                results.append({
                    "code": code, "action": "buy",
                    "quantity": quantity, "order_id": order_id,
                })

            elif signal == "sell" and code in current_positions:
                pos = current_positions[code]
                sell_qty = pos.get("can_use_volume", 0)
                if sell_qty > 0:
                    order_id = self.order_mgr.submit_order(
                        code=code, direction="sell", quantity=sell_qty
                    )
                    results.append({
                        "code": code, "action": "sell",
                        "quantity": sell_qty, "order_id": order_id,
                    })

        logger.info(f"执行 {len(results)} 条交易指令")
        return results

    def check_risk_and_stop(self) -> List[Dict]:
        """检查风控并执行止损/止盈"""
        positions = self.position_mgr.get_current_positions()
        actions = []

        for p in positions:
            code = p["code"]
            cost = p.get("open_price", 0)
            qty = p.get("volume", 0)
            market_val = p.get("market_value", 0)
            current_price = market_val / qty if qty > 0 else 0

            if self.risk.check_stop_loss(code, current_price, cost):
                sell_qty = p.get("can_use_volume", 0)
                if sell_qty > 0:
                    order_id = self.order_mgr.submit_order(
                        code=code, direction="sell", quantity=sell_qty
                    )
                    actions.append({"code": code, "action": "stop_loss", "order_id": order_id})

            elif self.risk.check_take_profit(code, current_price, cost):
                sell_qty = p.get("can_use_volume", 0)
                if sell_qty > 0:
                    order_id = self.order_mgr.submit_order(
                        code=code, direction="sell", quantity=sell_qty
                    )
                    actions.append({"code": code, "action": "take_profit", "order_id": order_id})

        return actions

    def daily_close(self):
        """收盘后处理: 记录持仓快照"""
        self.position_mgr.snapshot()
        logger.info("模拟盘: 收盘处理完成")
