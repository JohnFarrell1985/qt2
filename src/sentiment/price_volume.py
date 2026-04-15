"""Layer 1 量价情绪计算

从 stock_daily 表截面计算, 不产生任何网络请求。
这是 IC 最高的情绪来源, 零成本且最稳定。

指标:
- 涨跌比 (A/D Ratio)
- 涨停/跌停家数
- 炸板率
- 创 60 日新高/新低家数
- 市场波动率 (5/10/20 日)
- 缩放量强度
- 板块集中度
"""
from datetime import date, timedelta

import pandas as pd
from sqlalchemy import text

from src.common.db import get_session
from src.common.logger import get_logger

logger = get_logger(__name__)


class PriceVolumeCalculator:
    """Layer 1 量价情绪计算器"""

    def calculate(self, trade_date: date) -> dict:
        """计算指定日期的全部量价情绪指标

        Returns:
            dict with keys matching SentimentDaily Layer 1 fields
        """
        daily = self._load_daily_data(trade_date)
        if daily.empty:
            logger.warning(f"[量价情绪] {trade_date} 无行情数据")
            return {}

        history = self._load_history(trade_date, lookback_days=80)

        result = {}
        result.update(self._calc_ad_ratio(daily))
        result.update(self._calc_limit_counts(daily))
        result.update(self._calc_burst_rate(daily))
        result.update(self._calc_new_highs_lows(trade_date, history))
        result.update(self._calc_volatility(trade_date, history))
        result.update(self._calc_volume_ratio(trade_date, history))
        result.update(self._calc_sector_concentration(daily))

        logger.info(
            f"[量价情绪] {trade_date}: AD={result.get('ad_ratio', 0):.2f}, "
            f"涨停={result.get('limit_up_count', 0)}, "
            f"跌停={result.get('limit_down_count', 0)}"
        )
        return result

    def _load_daily_data(self, trade_date: date) -> pd.DataFrame:
        """加载指定日期全市场行情"""
        with get_session() as session:
            sql = text("""
                SELECT code, open, high, low, close, pre_close,
                       volume, amount, change_pct
                FROM stock_daily
                WHERE trade_date = :td AND volume > 0
            """)
            rows = session.execute(sql, {"td": trade_date}).fetchall()

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(rows, columns=[
            "code", "open", "high", "low", "close", "pre_close",
            "volume", "amount", "change_pct",
        ])

    def _load_history(
        self, trade_date: date, lookback_days: int = 80,
    ) -> pd.DataFrame:
        """加载近 N 天历史行情 (用于波动率/新高新低计算)"""
        start = trade_date - timedelta(days=lookback_days * 2)
        with get_session() as session:
            sql = text("""
                SELECT code, trade_date, close, volume, amount, change_pct
                FROM stock_daily
                WHERE trade_date BETWEEN :start AND :td AND volume > 0
                ORDER BY trade_date
            """)
            rows = session.execute(sql, {"start": start, "td": trade_date}).fetchall()

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(rows, columns=[
            "code", "trade_date", "close", "volume", "amount", "change_pct",
        ])

    @staticmethod
    def _calc_ad_ratio(daily: pd.DataFrame) -> dict:
        """涨跌比 (Advance/Decline Ratio)"""
        up = (daily["change_pct"] > 0).sum()
        down = (daily["change_pct"] < 0).sum()
        flat = (daily["change_pct"] == 0).sum()
        ad_ratio = up / max(down, 1)
        return {"ad_ratio": round(float(ad_ratio), 4)}

    @staticmethod
    def _calc_limit_counts(daily: pd.DataFrame) -> dict:
        """涨停/跌停家数"""
        limit_up = (daily["change_pct"] >= 9.8).sum()
        limit_down = (daily["change_pct"] <= -9.8).sum()
        return {
            "limit_up_count": int(limit_up),
            "limit_down_count": int(limit_down),
        }

    @staticmethod
    def _calc_burst_rate(daily: pd.DataFrame) -> dict:
        """炸板率: 曾触及涨停但未封住 / 涨停总数"""
        touched_limit = daily[daily["high"] >= daily["pre_close"] * 1.098]
        if touched_limit.empty:
            return {"burst_rate": 0.0}
        closed_limit = touched_limit[touched_limit["change_pct"] >= 9.8]
        burst = 1.0 - len(closed_limit) / len(touched_limit)
        return {"burst_rate": round(float(burst), 4)}

    @staticmethod
    def _calc_new_highs_lows(
        trade_date: date, history: pd.DataFrame,
    ) -> dict:
        """创 60 日新高/新低家数"""
        if history.empty:
            return {"new_high_60d": 0, "new_low_60d": 0}

        today_data = history[history["trade_date"] == trade_date]
        if today_data.empty:
            return {"new_high_60d": 0, "new_low_60d": 0}

        window_start = trade_date - timedelta(days=90)
        window = history[
            (history["trade_date"] >= window_start)
            & (history["trade_date"] <= trade_date)
        ]

        high_60d = window.groupby("code")["close"].max()
        low_60d = window.groupby("code")["close"].min()

        today_close = today_data.set_index("code")["close"]

        common_codes = today_close.index.intersection(high_60d.index)
        new_highs = (today_close[common_codes] >= high_60d[common_codes]).sum()
        new_lows = (today_close[common_codes] <= low_60d[common_codes]).sum()

        return {
            "new_high_60d": int(new_highs),
            "new_low_60d": int(new_lows),
        }

    @staticmethod
    def _calc_volatility(
        trade_date: date, history: pd.DataFrame,
    ) -> dict:
        """市场波动率 (全市场日收益率标准差)"""
        if history.empty:
            return {
                "market_volatility_5d": 0.0,
                "market_volatility_20d": 0.0,
            }

        daily_returns = history.groupby("trade_date")["change_pct"].std()
        daily_returns = daily_returns.sort_index()

        vol_5d = daily_returns.tail(5).mean() if len(daily_returns) >= 5 else 0.0
        vol_20d = daily_returns.tail(20).mean() if len(daily_returns) >= 20 else 0.0

        return {
            "market_volatility_5d": round(float(vol_5d), 4) if pd.notna(vol_5d) else 0.0,
            "market_volatility_20d": round(float(vol_20d), 4) if pd.notna(vol_20d) else 0.0,
        }

    @staticmethod
    def _calc_volume_ratio(
        trade_date: date, history: pd.DataFrame,
    ) -> dict:
        """缩放量强度: 今日全市场成交额 / 20 日均成交额"""
        if history.empty:
            return {"volume_ratio": 1.0}

        daily_amount = history.groupby("trade_date")["amount"].sum()
        daily_amount = daily_amount.sort_index()

        today_amount = daily_amount.get(trade_date, 0)
        ma20 = daily_amount.tail(21).head(20).mean() if len(daily_amount) >= 21 else daily_amount.mean()

        if ma20 and ma20 > 0:
            ratio = today_amount / ma20
        else:
            ratio = 1.0

        return {"volume_ratio": round(float(ratio), 4)}

    @staticmethod
    def _calc_sector_concentration(daily: pd.DataFrame) -> dict:
        """板块集中度 (需要板块数据, 暂用简化计算)

        简化版: 涨幅 Top 10% 股票的涨停占全市场涨停的比例。
        完整版需要 sector_stock 表配合。
        """
        limit_up = daily[daily["change_pct"] >= 9.8]
        if limit_up.empty:
            return {"sector_concentration": 0.0}

        total_limit = len(limit_up)
        top_decile = daily.nlargest(max(1, len(daily) // 10), "change_pct")
        top_limit = top_decile[top_decile["change_pct"] >= 9.8]

        concentration = len(top_limit) / max(total_limit, 1)
        return {"sector_concentration": round(float(concentration), 4)}
