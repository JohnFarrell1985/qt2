"""实盘交易引擎

与模拟盘共享相同的QMT API，仅账户类型不同。
实盘模式增加额外的风控确认。
"""
from typing import List, Dict, Optional

from src.common.logger import get_logger
from src.trading.paper_trading import PaperTradingEngine
from src.trading.qmt_trader import QMTTrader
from src.trading.risk_control import RiskController
from src.trading.order_manager import OrderManager
from src.trading.position_manager import PositionManager

logger = get_logger(__name__)


class LiveTradingEngine(PaperTradingEngine):
    """实盘交易引擎

    继承模拟盘逻辑，增加实盘安全检查。
    """

    def __init__(
        self,
        trader: Optional[QMTTrader] = None,
        risk_controller: Optional[RiskController] = None,
    ):
        super().__init__(trader, risk_controller)
        self.order_mgr = OrderManager(self.trader, account_type="live")
        self.position_mgr = PositionManager(self.trader, account_type="live")
        self._confirmed = False

    def confirm_live_mode(self) -> None:
        """确认进入实盘模式（安全防护）"""
        logger.warning("=== 实盘交易模式 ===")
        logger.warning("所有操作将产生真实交易，请确认风险。")
        self._confirmed = True

    def execute_signals(self, signals: List[Dict]) -> List[Dict]:
        """实盘执行交易信号（需先确认）"""
        if not self._confirmed:
            raise RuntimeError(
                "实盘模式未确认，请先调用 confirm_live_mode()"
            )
        return super().execute_signals(signals)

    def daily_close(self):
        """实盘收盘处理"""
        self.position_mgr.snapshot()
        logger.info("实盘: 收盘处理完成")
