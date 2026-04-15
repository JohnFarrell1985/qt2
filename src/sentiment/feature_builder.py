"""情绪特征工程 → LGB (P2-13)

将 SentimentDaily 表中的原始情绪指标转换为 ML 可用的特征:
- 滚动均值 (5/10/20日): 平滑噪声
- Z-score: 标准化可跨指标比较
- 差分: 捕捉变化速度
- 分位数分类 (恐慌/正常/过热): LGB 对分类特征更友好

P2-14 增强: 自动学习维度权重 (基于 LGB feature_importance)
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from src.common.config import settings
from src.common.db import get_session
from src.common.logger import get_logger

logger = get_logger(__name__)

_SENTIMENT_COLS = [
    "earning_effect", "capital_mood", "volatility_mood",
    "sector_heat", "news_mood", "global_mood",
    "composite_sentiment", "northbound_flow",
]

_ROLLING_WINDOWS = [5, 10, 20]


class SentimentFeatureBuilder:
    """情绪特征工程器"""

    def __init__(self, lookback_days: int = 60):
        self.lookback_days = lookback_days

    def build_features(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """构建情绪特征矩阵

        Args:
            start_date: 特征开始日期
            end_date: 特征结束日期

        Returns:
            DataFrame, index=trade_date, columns=特征名
        """
        fetch_start = start_date - timedelta(days=self.lookback_days + 30)
        raw = self._load_sentiment_data(fetch_start, end_date)
        if raw.empty:
            logger.warning("情绪数据为空, 无法构建特征")
            return pd.DataFrame()

        features = pd.DataFrame(index=raw.index)

        for col in _SENTIMENT_COLS:
            if col not in raw.columns:
                continue
            series = raw[col].astype(float)

            for w in _ROLLING_WINDOWS:
                features[f"{col}_ma{w}"] = series.rolling(w, min_periods=1).mean()
                features[f"{col}_std{w}"] = series.rolling(w, min_periods=1).std()

            roll_mean = series.rolling(20, min_periods=5).mean()
            roll_std = series.rolling(20, min_periods=5).std()
            features[f"{col}_zscore"] = (series - roll_mean) / roll_std.replace(0, np.nan)

            features[f"{col}_diff1"] = series.diff(1)
            features[f"{col}_diff5"] = series.diff(5)

            features[f"{col}_regime"] = pd.cut(
                series.rank(pct=True),
                bins=[0, 0.2, 0.8, 1.0],
                labels=[0, 1, 2],
                include_lowest=True,
            ).astype(float)

        features = features.loc[start_date:end_date]
        features = features.fillna(0)
        logger.info("情绪特征: %d 天 × %d 特征", len(features), features.shape[1])
        return features

    def _load_sentiment_data(self, start: date, end: date) -> pd.DataFrame:
        with get_session(readonly=True) as session:
            sql = text("""
                SELECT trade_date, earning_effect, capital_mood, volatility_mood,
                       sector_heat, news_mood, global_mood, composite_sentiment,
                       northbound_flow
                FROM sentiment_daily
                WHERE trade_date BETWEEN :s AND :e
                ORDER BY trade_date
            """)
            rows = session.execute(sql, {"s": start, "e": end}).fetchall()

        if not rows:
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["trade_date"] + _SENTIMENT_COLS)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df.set_index("trade_date")


class SentimentWeightLearner:
    """P2-14: 基于 LGB feature_importance 自动学习情绪维度权重

    替代 .env 中手动配置的 SENTIMENT_W_* 权重。
    """

    def learn_weights(
        self,
        features: pd.DataFrame,
        forward_returns: pd.Series,
    ) -> dict[str, float]:
        """用 LightGBM 学习各情绪维度的重要性, 转换为权重

        Args:
            features: SentimentFeatureBuilder.build_features 输出
            forward_returns: 对应日期的市场前向收益

        Returns:
            {dimension_name: weight} 字典, 权重和为 1
        """
        from lightgbm import LGBMRegressor

        aligned = features.join(forward_returns.rename("target"), how="inner").dropna()
        if len(aligned) < 50:
            logger.warning("样本不足 %d < 50, 无法学习权重", len(aligned))
            return {}

        X = aligned.drop(columns=["target"])
        y = aligned["target"]

        model = LGBMRegressor(
            n_estimators=200, num_leaves=31,
            learning_rate=0.05, verbose=-1,
        )
        model.fit(X, y)

        importance = pd.Series(model.feature_importances_, index=X.columns)

        dim_importance: dict[str, float] = {}
        for col in _SENTIMENT_COLS:
            dim_cols = [c for c in importance.index if c.startswith(col)]
            if dim_cols:
                dim_importance[col] = float(importance[dim_cols].sum())

        total = sum(dim_importance.values())
        if total <= 0:
            return {}

        weights = {k: round(v / total, 4) for k, v in dim_importance.items()}
        logger.info("自动学习情绪权重: %s", weights)
        return weights
