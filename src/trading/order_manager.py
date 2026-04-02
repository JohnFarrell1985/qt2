"""委托管理

管理下单、撤单、查询委托状态。
"""
from datetime import datetime
from typing import List, Dict, Optional

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import TradeOrder
from src.trading.qmt_trader import QMTTrader

logger = get_logger(__name__)


class OrderManager:
    """委托管理器"""

    def __init__(self, trader: QMTTrader, account_type: str = "paper"):
        self.trader = trader
        self.account_type = account_type

    def submit_order(
        self,
        code: str,
        direction: str,
        quantity: int,
        price: float = 0,
        price_type: str = "LATEST_PRICE",
    ) -> Optional[int]:
        """提交委托"""
        try:
            order_id = self.trader.order_stock(
                code=code,
                direction=direction,
                quantity=quantity,
                price_type=price_type,
                price=price,
            )

            with get_session() as session:
                record = TradeOrder(
                    order_id=str(order_id),
                    account_type=self.account_type,
                    code=code,
                    direction=direction,
                    quantity=quantity,
                    price=price,
                    price_type=price_type,
                    status="pending",
                )
                session.add(record)

            return order_id
        except Exception as e:
            logger.error(f"提交委托失败: {e}")
            return None

    def cancel_order(self, order_id: int) -> bool:
        """撤单"""
        try:
            result = self.trader.cancel_order(order_id)
            with get_session() as session:
                order = session.query(TradeOrder).filter_by(
                    order_id=str(order_id)
                ).first()
                if order:
                    order.status = "cancelled"
            return result == 0
        except Exception as e:
            logger.error(f"撤单失败: {e}")
            return False

    def get_today_orders(self) -> List[Dict]:
        """获取当日委托列表"""
        return self.trader.query_orders()
