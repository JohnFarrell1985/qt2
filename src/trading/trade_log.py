"""交易日志

记录每日交易绩效到数据库。
"""
from datetime import date
from typing import Optional

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import TradeDailyReport

logger = get_logger(__name__)


class TradeLogger:
    """交易日志记录器"""

    def __init__(self, account_type: str = "paper"):
        self.account_type = account_type
        self._initial_assets: Optional[float] = None

    def set_initial_assets(self, amount: float):
        self._initial_assets = amount

    def log_daily(
        self,
        report_date: date,
        total_assets: float,
        cash: float,
        market_value: float,
    ) -> None:
        """记录每日绩效"""
        daily_return = 0
        cumulative_return = 0

        with get_session() as session:
            prev = session.query(TradeDailyReport).filter(
                TradeDailyReport.account_type == self.account_type,
                TradeDailyReport.report_date < report_date,
            ).order_by(TradeDailyReport.report_date.desc()).first()

            if prev and prev.total_assets > 0:
                daily_return = (total_assets - prev.total_assets) / prev.total_assets * 100

            if self._initial_assets and self._initial_assets > 0:
                cumulative_return = (total_assets - self._initial_assets) / self._initial_assets * 100

            record = TradeDailyReport(
                report_date=report_date,
                account_type=self.account_type,
                total_assets=total_assets,
                cash=cash,
                market_value=market_value,
                daily_return=daily_return,
                cumulative_return=cumulative_return,
            )
            session.merge(record)

        logger.info(
            f"[{self.account_type}] {report_date} 总资产={total_assets:.2f} "
            f"日收益={daily_return:+.2f}% 累计={cumulative_return:+.2f}%"
        )
