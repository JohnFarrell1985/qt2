"""跨资产 Regime 上下文 (情绪引擎增强)

P1-37: 跨资产动量信号可显著改善 A 股择时 — 商品/利率/汇率信号
领先于 A 股 (散户反应滞后)。

监控资产:
  - 黄金 ETF (518880.SH): 避险情绪
  - 铜期货 (HG=F): 经济先行指标
  - VIX (^VIX): 全球恐慌指标
  - 美国 10 年国债 (^TNX): 利率环境
  - 美元/人民币 (USD/CNY): 资本流动

数据源: etf_daily (黄金 ETF), 或 sentiment_daily 中的外围字段
"""
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import text

from src.common.db import get_session
from src.common.logger import get_logger

logger = get_logger(__name__)


class CrossAssetRegime:
    """跨资产 Regime 信号 — 商品/债券/汇率/波动率"""

    CROSS_ASSETS = {
        "gold": "518880.SH",
    }

    def __init__(self, momentum_window: int = 20):
        self.momentum_window = momentum_window

    def compute(self, trade_date: date) -> dict:
        """计算跨资产 regime 上下文

        Returns:
            dict with per-asset momentum, cross_asset_risk_score, cross_asset_regime
        """
        signals = {}

        gold_mom = self._gold_momentum(trade_date)
        if gold_mom is not None:
            signals["gold_mom_20d"] = gold_mom

        sentiment_signals = self._load_sentiment_signals(trade_date)
        if sentiment_signals:
            if sentiment_signals.get("fx_usdcny_mom") is not None:
                signals["usdcny_mom_20d"] = sentiment_signals["fx_usdcny_mom"]
            if sentiment_signals.get("gold_price_mom") is not None:
                signals["gold_price_mom_20d"] = sentiment_signals["gold_price_mom"]

        if not signals:
            return {
                "cross_asset_risk_score": 0.5,
                "cross_asset_regime": "neutral",
            }

        risk_on_count = sum(1 for v in signals.values() if v > 0)
        total = len(signals)
        risk_score = risk_on_count / total if total > 0 else 0.5

        regime = (
            "risk_on" if risk_score > 0.6
            else "risk_off" if risk_score < 0.4
            else "neutral"
        )

        result = {
            **signals,
            "cross_asset_risk_score": round(risk_score, 3),
            "cross_asset_regime": regime,
        }

        logger.debug(f"[CrossAssetRegime] {trade_date}: score={risk_score:.2f}, regime={regime}")
        return result

    def _gold_momentum(self, trade_date: date) -> Optional[float]:
        """从 etf_daily 计算黄金 ETF 20 日动量"""
        code = self.CROSS_ASSETS["gold"]
        start = trade_date - timedelta(days=self.momentum_window * 3)
        with get_session() as session:
            sql = text("""
                SELECT trade_date, close
                FROM etf_daily
                WHERE code = :code
                  AND trade_date BETWEEN :start AND :td
                  AND close IS NOT NULL
                ORDER BY trade_date
            """)
            rows = session.execute(
                sql, {"code": code, "start": start, "td": trade_date}
            ).fetchall()

        if not rows or len(rows) < self.momentum_window:
            return None

        prices = pd.DataFrame(rows, columns=["trade_date", "close"])
        prices.set_index("trade_date", inplace=True)

        current = prices["close"].iloc[-1]
        past = prices["close"].iloc[-min(self.momentum_window, len(prices))]
        if past <= 0:
            return None
        return float(current / past - 1)

    def _load_sentiment_signals(self, trade_date: date) -> dict:
        """从 sentiment_daily 计算外围指标动量"""
        start = trade_date - timedelta(days=self.momentum_window * 3)
        with get_session() as session:
            sql = text("""
                SELECT trade_date, fx_usdcny, gold_price_usd
                FROM sentiment_daily
                WHERE trade_date BETWEEN :start AND :td
                ORDER BY trade_date
            """)
            rows = session.execute(sql, {"start": start, "td": trade_date}).fetchall()

        if not rows or len(rows) < 5:
            return {}

        df = pd.DataFrame(rows, columns=["trade_date", "fx_usdcny", "gold_price_usd"])
        df.set_index("trade_date", inplace=True)
        df = df.dropna(how="all")

        result = {}
        for col, key in [("fx_usdcny", "fx_usdcny_mom"), ("gold_price_usd", "gold_price_mom")]:
            if col in df.columns:
                clean = df[col].dropna()
                if len(clean) >= self.momentum_window:
                    current = clean.iloc[-1]
                    past = clean.iloc[-self.momentum_window]
                    if past > 0:
                        result[key] = float(current / past - 1)

        return result

    def compute_from_prices(self, prices: dict[str, pd.Series]) -> dict:
        """离线/测试接口: 直接提供价格序列"""
        signals = {}
        for name, series in prices.items():
            clean = series.dropna()
            if len(clean) < self.momentum_window:
                continue
            current = clean.iloc[-1]
            past = clean.iloc[-self.momentum_window]
            if past > 0:
                mom = current / past - 1
                signals[f"{name}_mom_{self.momentum_window}d"] = float(mom)

        if not signals:
            return {"cross_asset_risk_score": 0.5, "cross_asset_regime": "neutral"}

        risk_on_count = sum(1 for v in signals.values() if v > 0)
        risk_score = risk_on_count / len(signals)

        return {
            **signals,
            "cross_asset_risk_score": round(risk_score, 3),
            "cross_asset_regime": (
                "risk_on" if risk_score > 0.6
                else "risk_off" if risk_score < 0.4
                else "neutral"
            ),
        }
