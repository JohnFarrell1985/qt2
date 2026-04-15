"""情报信号 → 情绪引擎桥接

从 GlobalMarketSnapshot 查询全球市场数据, 计算 SentimentDaily 外围字段:
- fx_usdcny: 美元兑人民币汇率
- gold_price_usd: 黄金价格 (USD/oz)
- crude_oil_usd: 原油价格 (USD/bbl)
- global_mood: 外围情绪合成指数 (-1 ~ +1)
"""
from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.common.logger import get_logger
from src.data.models import GlobalMarketSnapshot
from src.sentiment.models import SentimentDaily

logger = get_logger(__name__)


def _clip(val: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


class SentimentBridge:
    """从 GlobalMarketSnapshot 计算并写入 SentimentDaily 外围字段。"""

    def __init__(self, session: Session):
        self._session = session

    def _latest_snapshots(self, trade_date: date) -> dict[str, dict]:
        """Query latest snapshot for each symbol on the given date.

        Returns dict keyed by symbol, e.g. {"SPX": {"close_price": 5000, "change_pct": 0.5}, ...}
        """
        stmt = (
            select(GlobalMarketSnapshot)
            .where(GlobalMarketSnapshot.trade_date == trade_date)
        )
        rows = self._session.execute(stmt).scalars().all()

        result: dict[str, dict] = {}
        for row in rows:
            existing = result.get(row.symbol)
            if existing is None or (
                row.collected_at
                and (
                    not existing.get("_collected_at")
                    or row.collected_at > existing["_collected_at"]
                )
            ):
                result[row.symbol] = {
                    "close_price": row.close_price,
                    "change_pct": row.change_pct,
                    "source": row.source,
                    "asset_class": row.asset_class,
                    "_collected_at": row.collected_at,
                }
        return result

    def compute_global_fields(self, trade_date: date) -> dict[str, Any]:
        """Compute sentiment fields from global market snapshots.

        Returns a dict with keys matching SentimentDaily columns:
        - fx_usdcny, gold_price_usd, crude_oil_usd, global_mood
        """
        snapshots = self._latest_snapshots(trade_date)
        if not snapshots:
            logger.warning("SentimentBridge: %s 无全球市场快照数据", trade_date)
            return {}

        fields: dict[str, Any] = {}

        if "USDCNY" in snapshots and snapshots["USDCNY"]["close_price"]:
            fields["fx_usdcny"] = snapshots["USDCNY"]["close_price"]

        if "XAUUSD" in snapshots and snapshots["XAUUSD"]["close_price"]:
            fields["gold_price_usd"] = snapshots["XAUUSD"]["close_price"]

        wti = snapshots.get("WTI", {})
        brent = snapshots.get("BRENT", {})
        oil_price = wti.get("close_price") or brent.get("close_price")
        if oil_price:
            fields["crude_oil_usd"] = oil_price

        mood_score = 0.0
        mood_signals = 0

        spx = snapshots.get("SPX", {})
        spx_chg = spx.get("change_pct")
        if spx_chg is not None:
            if spx_chg > 1.0:
                mood_score += 0.3
            elif spx_chg > 0.3:
                mood_score += 0.15
            elif spx_chg < -1.0:
                mood_score -= 0.3
            elif spx_chg < -0.3:
                mood_score -= 0.15
            mood_signals += 1

        vix = snapshots.get("VIX", {})
        vix_close = vix.get("close_price")
        if vix_close is not None:
            if vix_close > 30:
                mood_score -= 0.25
            elif vix_close > 20:
                mood_score -= 0.1
            elif vix_close < 15:
                mood_score += 0.1
            mood_signals += 1

        gold = snapshots.get("XAUUSD", {})
        gold_chg = gold.get("change_pct")
        if gold_chg is not None:
            if gold_chg > 1.5:
                mood_score -= 0.15
            elif gold_chg < -1.0:
                mood_score += 0.1
            mood_signals += 1

        cny = snapshots.get("USDCNY", {})
        cny_chg = cny.get("change_pct")
        if cny_chg is not None:
            if cny_chg > 0.3:
                mood_score -= 0.2
            elif cny_chg < -0.3:
                mood_score += 0.15
            mood_signals += 1

        a50 = snapshots.get("FTSE_A50", {})
        a50_chg = a50.get("change_pct")
        if a50_chg is not None:
            if a50_chg > 1.0:
                mood_score += 0.3
            elif a50_chg > 0.3:
                mood_score += 0.15
            elif a50_chg < -1.0:
                mood_score -= 0.3
            elif a50_chg < -0.3:
                mood_score -= 0.15
            mood_signals += 1

        if mood_signals > 0:
            fields["global_mood"] = _clip(mood_score)

        logger.info(
            "SentimentBridge: %s computed %d fields from %d snapshots (%d signals)",
            trade_date, len(fields), len(snapshots), mood_signals,
        )
        return fields

    def update_sentiment_daily(self, trade_date: date) -> dict[str, Any]:
        """Compute global fields and upsert into SentimentDaily."""
        fields = self.compute_global_fields(trade_date)
        if not fields:
            return {}

        existing = self._session.get(SentimentDaily, trade_date)
        if existing:
            for key, value in fields.items():
                setattr(existing, key, value)
        else:
            row = SentimentDaily(trade_date=trade_date, **fields)
            self._session.add(row)

        self._session.flush()
        logger.info("SentimentBridge: %s sentiment_daily updated with %d fields", trade_date, len(fields))
        return fields
