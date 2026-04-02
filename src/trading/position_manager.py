"""持仓管理

查询持仓、记录每日快照。
"""
from datetime import date, datetime
from typing import List, Dict

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import TradePosition
from src.trading.qmt_trader import QMTTrader

logger = get_logger(__name__)


class PositionManager:
    """持仓管理器"""

    def __init__(self, trader: QMTTrader, account_type: str = "paper"):
        self.trader = trader
        self.account_type = account_type

    def get_current_positions(self) -> List[Dict]:
        """获取当前持仓"""
        return self.trader.query_positions()

    def snapshot(self) -> int:
        """保存今日持仓快照"""
        positions = self.get_current_positions()
        today = date.today()
        count = 0

        with get_session() as session:
            for p in positions:
                cost = p.get("open_price", 0)
                market_val = p.get("market_value", 0)
                qty = p.get("volume", 0)
                current_price = market_val / qty if qty > 0 else 0
                profit = market_val - cost * qty if cost > 0 else 0
                profit_pct = (current_price / cost - 1) * 100 if cost > 0 else 0

                record = TradePosition(
                    snapshot_date=today,
                    account_type=self.account_type,
                    code=p["code"],
                    quantity=qty,
                    cost_price=cost,
                    market_price=current_price,
                    market_value=market_val,
                    profit=profit,
                    profit_pct=profit_pct,
                )
                session.add(record)
                count += 1

        logger.info(f"已保存 {count} 条持仓快照")
        return count

    def get_total_market_value(self) -> float:
        """获取总持仓市值"""
        positions = self.get_current_positions()
        return sum(p.get("market_value", 0) for p in positions)
