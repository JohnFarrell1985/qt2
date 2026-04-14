"""合成情绪指数 (Composite Sentiment Index)

将 6-8 个维度加权合成为单一情绪指数:
  CSI = Σ(wi × dimension_i),  范围 -1.0 (极度恐慌) ~ +1.0 (极度贪婪)

P1-16: 核心合成逻辑 + 特征工程
"""
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from src.common.config import settings
from src.common.db import get_session
from src.common.logger import get_logger

logger = get_logger(__name__)


def _zscore(x: float, mean: float, std: float) -> float:
    """计算 Z-score, 裁剪到 [-3, 3] 再归一化到 [-1, 1]"""
    if std <= 0 or np.isnan(std):
        return 0.0
    z = (x - mean) / std
    z = np.clip(z, -3.0, 3.0)
    return float(z / 3.0)


class CompositeIndex:
    """合成情绪指数计算器

    6 维标准维度 + 2 维研究驱动增强 (P1-33 北向资金, P1-37 跨资产):
        earning_effect   — 赚钱效应 (涨跌比 + 涨停 + 新高)
        capital_mood     — 资金情绪 (北向 + 融资余额变化)
        volatility_mood  — 波动情绪 (市场波动率 + 跌停 + 缩量)
        sector_heat      — 板块热度 (集中度)
        news_mood        — 新闻情绪 (LLM 清洗后)
        global_mood      — 外围情绪 (汇率 + 黄金 + 原油)
        northbound_flow  — 北向资金流 (P1-33, 可选)
        cross_asset      — 跨资产 regime (P1-37, 可选)
    """

    def __init__(self):
        cfg = settings.sentiment
        self.weights = {
            "earning_effect": cfg.w_earning,
            "capital_mood": cfg.w_capital,
            "volatility_mood": cfg.w_volatility,
            "sector_heat": cfg.w_sector,
            "news_mood": cfg.w_news,
            "global_mood": cfg.w_global,
            "northbound_flow": cfg.w_northbound,
        }

    def compute(self, trade_date: date) -> dict:
        """计算指定日期的合成情绪指数

        Returns:
            dict 含各维度得分和合成指数 CSI
        """
        raw = self._load_sentiment_row(trade_date)
        if not raw:
            logger.warning(f"[CSI] {trade_date} 无情绪数据")
            return {}

        history = self._load_history(trade_date, lookback_days=60)

        dimensions = {}
        dimensions["earning_effect"] = self._calc_earning_effect(raw, history)
        dimensions["capital_mood"] = self._calc_capital_mood(raw, history)
        dimensions["volatility_mood"] = self._calc_volatility_mood(raw, history)
        dimensions["sector_heat"] = self._calc_sector_heat(raw, history)
        dimensions["news_mood"] = self._calc_news_mood(raw)
        dimensions["global_mood"] = self._calc_global_mood(raw, history)
        dimensions["northbound_flow"] = self._calc_northbound_flow(raw, history)

        csi = sum(
            self.weights.get(k, 0) * v
            for k, v in dimensions.items()
            if v is not None
        )
        total_weight = sum(
            self.weights.get(k, 0)
            for k, v in dimensions.items()
            if v is not None
        )
        if total_weight > 0:
            csi = csi / total_weight
        csi = float(np.clip(csi, -1.0, 1.0))

        dimensions["composite_sentiment"] = csi
        logger.info(f"[CSI] {trade_date}: CSI={csi:.3f}")
        return dimensions

    def _load_sentiment_row(self, trade_date: date) -> Optional[dict]:
        with get_session() as session:
            sql = text("""
                SELECT ad_ratio, limit_up_count, limit_down_count,
                       burst_rate, new_high_60d, new_low_60d,
                       market_volatility_5d, market_volatility_20d,
                       volume_ratio, sector_concentration,
                       north_net_flow, margin_balance_change,
                       news_sentiment_score,
                       fx_usdcny, gold_price_usd, crude_oil_usd
                FROM sentiment_daily
                WHERE trade_date = :td
            """)
            row = session.execute(sql, {"td": trade_date}).fetchone()
        if not row:
            return None
        cols = [
            "ad_ratio", "limit_up_count", "limit_down_count",
            "burst_rate", "new_high_60d", "new_low_60d",
            "market_volatility_5d", "market_volatility_20d",
            "volume_ratio", "sector_concentration",
            "north_net_flow", "margin_balance_change",
            "news_sentiment_score",
            "fx_usdcny", "gold_price_usd", "crude_oil_usd",
        ]
        return dict(zip(cols, row))

    def _load_history(self, trade_date: date, lookback_days: int = 60) -> pd.DataFrame:
        start = trade_date - timedelta(days=lookback_days * 2)
        with get_session() as session:
            sql = text("""
                SELECT trade_date, ad_ratio, limit_up_count, limit_down_count,
                       new_high_60d, new_low_60d,
                       market_volatility_5d, market_volatility_20d,
                       volume_ratio, sector_concentration,
                       north_net_flow, margin_balance_change,
                       news_sentiment_score,
                       fx_usdcny, gold_price_usd, crude_oil_usd
                FROM sentiment_daily
                WHERE trade_date BETWEEN :start AND :td
                ORDER BY trade_date
            """)
            rows = session.execute(sql, {"start": start, "td": trade_date}).fetchall()
        if not rows:
            return pd.DataFrame()
        cols = [
            "trade_date", "ad_ratio", "limit_up_count", "limit_down_count",
            "new_high_60d", "new_low_60d",
            "market_volatility_5d", "market_volatility_20d",
            "volume_ratio", "sector_concentration",
            "north_net_flow", "margin_balance_change",
            "news_sentiment_score",
            "fx_usdcny", "gold_price_usd", "crude_oil_usd",
        ]
        df = pd.DataFrame(rows, columns=cols)
        df.set_index("trade_date", inplace=True)
        return df

    @staticmethod
    def _safe_zscore(current: Optional[float], series: pd.Series) -> float:
        if current is None or pd.isna(current):
            return 0.0
        clean = series.dropna()
        if len(clean) < 5:
            return 0.0
        return _zscore(current, clean.mean(), clean.std())

    def _calc_earning_effect(self, raw: dict, hist: pd.DataFrame) -> float:
        """赚钱效应: 涨跌比 + 涨停数 + 新高数"""
        scores = []
        if raw.get("ad_ratio") is not None and "ad_ratio" in hist.columns:
            scores.append(self._safe_zscore(raw["ad_ratio"], hist["ad_ratio"]))
        if raw.get("limit_up_count") is not None and "limit_up_count" in hist.columns:
            scores.append(self._safe_zscore(raw["limit_up_count"], hist["limit_up_count"]))
        if raw.get("new_high_60d") is not None and "new_high_60d" in hist.columns:
            scores.append(self._safe_zscore(raw["new_high_60d"], hist["new_high_60d"]))
        return float(np.mean(scores)) if scores else 0.0

    def _calc_capital_mood(self, raw: dict, hist: pd.DataFrame) -> float:
        """资金情绪: 北向净流入 + 融资余额变化"""
        scores = []
        if raw.get("north_net_flow") is not None and "north_net_flow" in hist.columns:
            scores.append(self._safe_zscore(raw["north_net_flow"], hist["north_net_flow"]))
        if raw.get("margin_balance_change") is not None and "margin_balance_change" in hist.columns:
            scores.append(self._safe_zscore(raw["margin_balance_change"], hist["margin_balance_change"]))
        return float(np.mean(scores)) if scores else 0.0

    def _calc_volatility_mood(self, raw: dict, hist: pd.DataFrame) -> float:
        """波动情绪: 高波动 = 恐慌 (反向)"""
        scores = []
        if raw.get("market_volatility_20d") is not None and "market_volatility_20d" in hist.columns:
            scores.append(-self._safe_zscore(raw["market_volatility_20d"], hist["market_volatility_20d"]))
        if raw.get("limit_down_count") is not None and "limit_down_count" in hist.columns:
            scores.append(-self._safe_zscore(raw["limit_down_count"], hist["limit_down_count"]))
        if raw.get("volume_ratio") is not None and "volume_ratio" in hist.columns:
            scores.append(self._safe_zscore(raw["volume_ratio"], hist["volume_ratio"]))
        return float(np.mean(scores)) if scores else 0.0

    def _calc_sector_heat(self, raw: dict, hist: pd.DataFrame) -> float:
        """板块热度"""
        if raw.get("sector_concentration") is not None and "sector_concentration" in hist.columns:
            return self._safe_zscore(raw["sector_concentration"], hist["sector_concentration"])
        return 0.0

    @staticmethod
    def _calc_news_mood(raw: dict) -> float:
        """新闻情绪 (已经是 -1~+1, 直接使用)"""
        val = raw.get("news_sentiment_score")
        if val is None or np.isnan(val):
            return 0.0
        return float(np.clip(val, -1.0, 1.0))

    def _calc_global_mood(self, raw: dict, hist: pd.DataFrame) -> float:
        """外围情绪: 汇率(反向) + 黄金 + 原油"""
        scores = []
        if raw.get("fx_usdcny") is not None and "fx_usdcny" in hist.columns:
            scores.append(-self._safe_zscore(raw["fx_usdcny"], hist["fx_usdcny"]))
        if raw.get("gold_price_usd") is not None and "gold_price_usd" in hist.columns:
            scores.append(self._safe_zscore(raw["gold_price_usd"], hist["gold_price_usd"]))
        return float(np.mean(scores)) if scores else 0.0

    def _calc_northbound_flow(self, raw: dict, hist: pd.DataFrame) -> Optional[float]:
        """北向资金流 (P1-33): 5 日净流入 Z-score"""
        if "north_net_flow" not in hist.columns:
            return None
        clean = hist["north_net_flow"].dropna()
        if len(clean) < 10:
            return None
        flow_5d = clean.rolling(5, min_periods=1).sum()
        current = flow_5d.iloc[-1] if len(flow_5d) > 0 else None
        if current is None:
            return None
        return _zscore(current, flow_5d.mean(), flow_5d.std())
