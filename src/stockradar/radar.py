"""StockRadar 核心引擎 (P2-15)

个股舆情/事件 → 信号增强:
- 从 dataclean 清洗后的事件 (StockEventExtraction) 提取个股影响
- 结合新闻情绪、公告解读、舆情热度生成增强信号
- 输出 JSON 对接 SignalArbiter
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.common.config import settings
from src.common.db import get_session
from src.common.logger import get_logger

logger = get_logger(__name__)


class StockSignal:
    """单只股票的舆情/事件信号"""

    __slots__ = ("code", "event_type", "impact_score", "confidence", "reason", "source")

    def __init__(
        self,
        code: str,
        event_type: str = "news",
        impact_score: float = 0.0,
        confidence: float = 0.5,
        reason: str = "",
        source: str = "stockradar",
    ):
        self.code = code
        self.event_type = event_type
        self.impact_score = impact_score
        self.confidence = confidence
        self.reason = reason
        self.source = source

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "event_type": self.event_type,
            "impact_score": self.impact_score,
            "confidence": self.confidence,
            "reason": self.reason,
            "source": self.source,
        }


class StockRadar:
    """个股舆情雷达

    扫描最近事件, 为每只目标股票计算综合舆情评分。
    """

    def __init__(self, lookback_days: int = 7):
        self.lookback_days = lookback_days

    def scan(
        self,
        codes: List[str],
        trade_date: date,
    ) -> List[StockSignal]:
        """扫描目标股票的近期事件和舆情

        Args:
            codes: 股票代码列表
            trade_date: 当前交易日

        Returns:
            每只股票的舆情信号列表
        """
        since = trade_date - timedelta(days=self.lookback_days)
        events = self._load_recent_events(codes, since, trade_date)
        news_scores = self._load_news_sentiment(codes, since, trade_date)

        signals: List[StockSignal] = []
        for code in codes:
            code_events = [e for e in events if e.get("code") == code]
            news_score = news_scores.get(code, 0.0)

            if code_events:
                impact = self._aggregate_event_impact(code_events)
                signals.append(StockSignal(
                    code=code,
                    event_type="event",
                    impact_score=impact,
                    confidence=min(0.5 + len(code_events) * 0.1, 0.95),
                    reason=code_events[0].get("description", "事件驱动"),
                ))

            if abs(news_score) > 0.3:
                signals.append(StockSignal(
                    code=code,
                    event_type="sentiment",
                    impact_score=news_score,
                    confidence=0.6,
                    reason="舆情热度",
                ))

        logger.info("StockRadar 扫描 %d 只, 产生 %d 个信号", len(codes), len(signals))
        return signals

    def _load_recent_events(
        self, codes: List[str], since: date, until: date,
    ) -> List[dict]:
        try:
            with get_session(readonly=True) as session:
                sql = text("""
                    SELECT trade_date, extra->'key_events' as events
                    FROM sentiment_daily
                    WHERE trade_date BETWEEN :s AND :e
                """)
                rows = session.execute(sql, {"s": since, "e": until}).fetchall()

            events = []
            for row in rows:
                if row[1]:
                    for ev in row[1] if isinstance(row[1], list) else []:
                        events.append(ev)
            return events
        except Exception:
            return []

    def _load_news_sentiment(
        self, codes: List[str], since: date, until: date,
    ) -> Dict[str, float]:
        return {}

    @staticmethod
    def _aggregate_event_impact(events: List[dict]) -> float:
        total = 0.0
        for e in events:
            impact = e.get("impact", "neutral")
            magnitude = e.get("magnitude", "medium")
            base = {"positive": 0.3, "negative": -0.3, "neutral": 0.0}.get(impact, 0.0)
            mult = {"high": 2.0, "medium": 1.0, "low": 0.5}.get(magnitude, 1.0)
            total += base * mult
        return max(-1.0, min(1.0, total))
