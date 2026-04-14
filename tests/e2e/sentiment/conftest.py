"""Sentiment P1-2 E2E — conftest

CrossAssetRegime 的黄金动量部分使用真实 etf_daily (518880.SH) 数据;
CompositeIndex / MacroClassifier / NorthboundFlow 因 sentiment_daily 为空,
使用模块提供的离线接口 (compute_from_series / classify) 或在隔离 schema 注入数据。
"""
import pytest
import pandas as pd
import numpy as np
from sqlalchemy import create_engine, text

from src.common.config import settings


@pytest.fixture(scope="session")
def pg_engine():
    engine = create_engine(
        settings.database.url,
        pool_size=3,
        max_overflow=5,
        pool_pre_ping=True,
    )
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def real_gold_etf_prices(pg_engine) -> pd.DataFrame:
    """黄金 ETF (518880.SH) 最近一年价格 — CrossAssetRegime 用"""
    sql = """
    SELECT trade_date, close
    FROM etf_daily
    WHERE code = '518880.SH' AND trade_date >= '2025-04-14'
    ORDER BY trade_date
    """
    with pg_engine.connect() as conn:
        df = pd.read_sql(text(sql), conn)
    if df.empty:
        pytest.skip("518880.SH 无数据")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df.set_index("trade_date", inplace=True)
    return df


@pytest.fixture(scope="session")
def synthetic_northbound_flow() -> pd.Series:
    """合成北向资金流序列 — 模拟 60 天真实数据模式"""
    np.random.seed(42)
    dates = pd.bdate_range(start="2026-01-01", periods=80)
    base_flow = np.cumsum(np.random.randn(80) * 10)
    flow = pd.Series(base_flow + np.random.randn(80) * 5, index=dates, name="north_net_flow")
    return flow


@pytest.fixture(scope="session")
def synthetic_sentiment_features() -> dict[str, float]:
    """合成情绪特征 — MacroClassifier 分类测试用"""
    return {
        "ad_ratio": 1.3,
        "ad_ratio_ma5": 1.25,
        "limit_up_count": 60,
        "limit_down_count": 15,
        "limit_down_ma5": 12.0,
        "new_high_60d": 90,
        "new_high_60d_ma5": 85.0,
        "new_low_60d": 20,
        "new_low_60d_ma5": 22.0,
        "market_volatility_5d": 0.015,
        "market_volatility_20d": 0.018,
        "volume_ratio": 1.2,
        "volume_ratio_ma5": 1.15,
        "sector_concentration": 0.3,
        "north_net_flow": 50.0,
        "margin_balance_change": 100.0,
        "news_sentiment_score": 0.3,
        "fx_usdcny": 7.2,
        "gold_price_usd": 2400.0,
        "crude_oil_usd": 75.0,
        "earning_effect": 0.4,
        "earning_effect_ma5": 0.35,
        "capital_mood": 0.3,
        "capital_mood_ma5": 0.25,
        "capital_mood_diff5": 0.1,
        "volatility_mood": -0.1,
        "volatility_mood_ma5": -0.15,
        "sector_heat": 0.2,
        "news_mood": 0.3,
        "global_mood": 0.1,
        "composite_sentiment": 0.35,
        "composite_sentiment_diff5": 0.15,
        "ad_ratio_diff5": 0.2,
    }
