"""资金流向深度分析器 (P2-16)

北向资金、融资融券、主力大单三个维度, 构建"聪明钱"跟随信号。
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np
from sqlalchemy import text

from src.common.db import get_session
from src.common.logger import get_logger

logger = get_logger(__name__)


class FundFlowSignal:
    """资金流向信号"""

    __slots__ = ("code", "dimension", "score", "amount", "description")

    def __init__(
        self,
        code: str = "market",
        dimension: str = "northbound",
        score: float = 0.0,
        amount: float = 0.0,
        description: str = "",
    ):
        self.code = code
        self.dimension = dimension
        self.score = score
        self.amount = amount
        self.description = description

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "dimension": self.dimension,
            "score": self.score,
            "amount": self.amount,
            "description": self.description,
        }


class FundFlowAnalyzer:
    """资金流向分析器

    三维度分析:
    1. 北向资金: 净流入/流出量 + 5/10/20 日累计
    2. 融资融券: 余额变化趋势
    3. 主力大单: 大单净买入 (需要 Level2 数据)
    """

    def __init__(self, lookback_days: int = 20):
        self.lookback_days = lookback_days

    def analyze(self, trade_date: date) -> List[FundFlowSignal]:
        """分析指定日期的资金流向

        Returns:
            资金流向信号列表
        """
        signals: List[FundFlowSignal] = []

        north = self._analyze_northbound(trade_date)
        if north:
            signals.append(north)

        return signals

    def _analyze_northbound(self, trade_date: date) -> Optional[FundFlowSignal]:
        """分析北向资金"""
        try:
            with get_session(readonly=True) as session:
                sql = text("""
                    SELECT trade_date, northbound_flow
                    FROM sentiment_daily
                    WHERE trade_date <= :d
                    ORDER BY trade_date DESC
                    LIMIT :n
                """)
                rows = session.execute(
                    sql, {"d": trade_date, "n": self.lookback_days}
                ).fetchall()

            if not rows:
                return None

            flows = [float(r[1] or 0) for r in rows]
            today = flows[0]
            ma5 = np.mean(flows[:5]) if len(flows) >= 5 else today
            ma20 = np.mean(flows[:20]) if len(flows) >= 20 else ma5

            if today > 0 and ma5 > 0:
                score = min(1.0, today / 100 * 0.3 + (1 if ma5 > 0 else -1) * 0.3)
            elif today < 0 and ma5 < 0:
                score = max(-1.0, today / 100 * 0.3 + (1 if ma5 > 0 else -1) * 0.3)
            else:
                score = 0.0

            direction = "流入" if today > 0 else "流出"
            return FundFlowSignal(
                code="market",
                dimension="northbound",
                score=round(score, 2),
                amount=today,
                description=f"北向资金今日净{direction}{abs(today):.1f}亿, 5日均值{ma5:.1f}亿",
            )
        except Exception as e:
            logger.warning("北向资金分析失败: %s", e)
            return None

    def get_smart_money_score(self, trade_date: date) -> float:
        """综合聪明钱评分 [-1, 1]"""
        signals = self.analyze(trade_date)
        if not signals:
            return 0.0
        return round(np.mean([s.score for s in signals]), 2)
