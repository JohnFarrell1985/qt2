"""数据新鲜度监控 — 检测各核心表最新数据是否及时

支持 exchange_calendars 交易日历, 缺失时降级为工作日判断。
"""
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FreshnessAlert:
    """数据滞后告警。"""

    table: str
    latest_date: date | None
    expected_date: date
    lag_days: int
    threshold_days: int


class DataFreshnessMonitor:
    """核心表数据新鲜度监控。

    CORE_TABLES 定义每张表允许的最大交易日延迟天数。
    """

    CORE_TABLES: dict[str, int] = {
        "stock_daily": 1,
        "market_index": 1,
        "sector_data": 2,
        "stock_financial_report": 30,
    }

    def __init__(self, calendar_name: str = "XSHG"):
        self._calendar = None
        self._calendar_name = calendar_name
        try:
            import exchange_calendars
            self._calendar = exchange_calendars.get_calendar(calendar_name)
            logger.info("exchange_calendars loaded: %s", calendar_name)
        except (ImportError, Exception) as exc:
            logger.warning(
                "exchange_calendars unavailable (%s), falling back to weekday heuristic",
                exc,
            )

    def check_all(self, session: Session) -> list[FreshnessAlert]:
        """检查所有核心表。非交易日跳过检查。"""
        today = date.today()
        if not self._is_trading_day(today):
            logger.info("today %s is not a trading day, skipping freshness check", today)
            return []

        alerts: list[FreshnessAlert] = []
        for table, threshold in self.CORE_TABLES.items():
            alert = self.check_table(session, table, threshold)
            if alert is not None:
                alerts.append(alert)

        if alerts:
            logger.warning("freshness alerts: %d table(s) stale", len(alerts))
        else:
            logger.info("all core tables fresh")
        return alerts

    def check_table(self, session: Session, table: str, max_lag: int) -> FreshnessAlert | None:
        """检查单张表的新鲜度。"""
        today = date.today()

        date_col = "report_date" if table == "stock_financial_report" else "trade_date"
        query = text(f"SELECT MAX({date_col}) FROM {table}")  # noqa: S608
        result = session.execute(query).scalar()

        latest: date | None = None
        if result is not None:
            if isinstance(result, _dt.datetime):
                latest = result.date()
            elif isinstance(result, _dt.date):
                latest = result

        expected = self._last_trading_day(today)
        if latest is None:
            lag = max_lag + 1
        else:
            lag = self._trading_days_between(latest, today)

        if lag > max_lag:
            alert = FreshnessAlert(
                table=table,
                latest_date=latest,
                expected_date=expected,
                lag_days=lag,
                threshold_days=max_lag,
            )
            logger.warning(
                "stale: %s latest=%s expected=%s lag=%d threshold=%d",
                table, latest, expected, lag, max_lag,
            )
            return alert
        return None

    def _trading_days_between(self, start: date, end: date) -> int:
        """计算 start 和 end 之间的交易日数量 (不含 start, 含 end)。"""
        if start >= end:
            return 0

        if self._calendar is not None:
            import pandas as pd
            sessions = self._calendar.sessions_in_range(
                pd.Timestamp(start + timedelta(days=1)),
                pd.Timestamp(end),
            )
            return len(sessions)

        count = 0
        current = start + timedelta(days=1)
        while current <= end:
            if current.weekday() < 5:
                count += 1
            current += timedelta(days=1)
        return count

    def _is_trading_day(self, d: date) -> bool:
        """判断给定日期是否为交易日。"""
        if self._calendar is not None:
            import pandas as pd
            return self._calendar.is_session(pd.Timestamp(d))

        return d.weekday() < 5

    _MAX_LOOKBACK_DAYS: int = 10

    def _last_trading_day(self, d: date) -> date:
        """获取 d 当天或之前最近的交易日。"""
        current = d
        for _ in range(self._MAX_LOOKBACK_DAYS):
            if self._is_trading_day(current):
                return current
            current -= timedelta(days=1)
        return current
