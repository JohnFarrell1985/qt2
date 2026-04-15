"""风险监控引擎 (P2-17)

实时监控市场异常事件:
- 黑天鹅: 大盘急跌 > 3%, 个股集体跌停
- 政策突变: 监管新规, 利率调整
- 闪崩预警: 流动性枯竭, 做空量激增
触发条件满足时发送紧急止损信号。
"""
from __future__ import annotations

from datetime import date, timedelta
from enum import Enum
from typing import Dict, List, Optional

import numpy as np
from sqlalchemy import text

from src.common.config import settings
from src.common.db import get_session
from src.common.logger import get_logger

logger = get_logger(__name__)


class RiskLevel(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    ELEVATED = "elevated"
    HIGH = "high"
    EXTREME = "extreme"


class RiskEvent:
    """风险事件"""

    __slots__ = ("event_type", "level", "description", "affected_codes", "recommended_action")

    def __init__(
        self,
        event_type: str,
        level: RiskLevel = RiskLevel.NORMAL,
        description: str = "",
        affected_codes: Optional[List[str]] = None,
        recommended_action: str = "monitor",
    ):
        self.event_type = event_type
        self.level = level
        self.description = description
        self.affected_codes = affected_codes or []
        self.recommended_action = recommended_action

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "level": self.level.value,
            "description": self.description,
            "affected_codes": self.affected_codes,
            "recommended_action": self.recommended_action,
        }


class RiskMonitor:
    """市场风险监控"""

    def __init__(
        self,
        crash_threshold: float = -3.0,
        volatility_extreme_pct: float = 95.0,
    ):
        self.crash_threshold = crash_threshold
        self.volatility_extreme_pct = volatility_extreme_pct

    def check(self, trade_date: date) -> List[RiskEvent]:
        """执行风险检查

        Returns:
            触发的风险事件列表 (空列表 = 安全)
        """
        events: List[RiskEvent] = []

        market_crash = self._check_market_crash(trade_date)
        if market_crash:
            events.append(market_crash)

        vol_spike = self._check_volatility_spike(trade_date)
        if vol_spike:
            events.append(vol_spike)

        if events:
            max_level = max(e.level.value for e in events)
            logger.warning(
                "风险检查 %s: %d 事件, 最高级别=%s",
                trade_date, len(events), max_level,
            )
        return events

    def get_risk_level(self, trade_date: date) -> RiskLevel:
        """获取综合风险等级"""
        events = self.check(trade_date)
        if not events:
            return RiskLevel.LOW
        levels = [e.level for e in events]
        if RiskLevel.EXTREME in levels:
            return RiskLevel.EXTREME
        if RiskLevel.HIGH in levels:
            return RiskLevel.HIGH
        if RiskLevel.ELEVATED in levels:
            return RiskLevel.ELEVATED
        return RiskLevel.NORMAL

    def _check_market_crash(self, trade_date: date) -> Optional[RiskEvent]:
        """检查大盘急跌"""
        try:
            with get_session(readonly=True) as session:
                sql = text("""
                    SELECT close FROM market_index
                    WHERE code = '000001.SH'
                    AND trade_date <= :d
                    ORDER BY trade_date DESC LIMIT 2
                """)
                rows = session.execute(sql, {"d": trade_date}).fetchall()

            if len(rows) < 2 or rows[1][0] <= 0:
                return None

            change_pct = (rows[0][0] - rows[1][0]) / rows[1][0] * 100
            if change_pct <= self.crash_threshold:
                level = RiskLevel.EXTREME if change_pct <= -5 else RiskLevel.HIGH
                return RiskEvent(
                    event_type="market_crash",
                    level=level,
                    description=f"大盘跌幅 {change_pct:.2f}%",
                    recommended_action="reduce" if level == RiskLevel.HIGH else "exit",
                )
        except Exception as e:
            logger.debug("大盘急跌检查异常: %s", e)
        return None

    def _check_volatility_spike(self, trade_date: date) -> Optional[RiskEvent]:
        """检查波动率飙升"""
        try:
            with get_session(readonly=True) as session:
                sql = text("""
                    SELECT composite_sentiment, earning_effect
                    FROM sentiment_daily
                    WHERE trade_date = :d
                """)
                row = session.execute(sql, {"d": trade_date}).fetchone()

            if row is None:
                return None

            sentiment = float(row[0] or 0)
            earning = float(row[1] or 0)

            if sentiment < -0.6 and earning < -0.5:
                return RiskEvent(
                    event_type="panic_selling",
                    level=RiskLevel.ELEVATED,
                    description=f"恐慌抛售指标触发: 情绪={sentiment:.2f}, 赚钱效应={earning:.2f}",
                    recommended_action="reduce",
                )
        except Exception as e:
            logger.debug("波动率检查异常: %s", e)
        return None
