"""Portfolio E2E — conftest

直连生产 PostgreSQL (public schema), 使用真实 etf_daily / stock_daily 数据。
"""
import pytest
import pandas as pd
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
def real_etf_price_matrix(pg_engine) -> pd.DataFrame:
    """5 只 ETF 的收盘价矩阵 — 组合优化用"""
    codes = ["510300.SH", "510500.SH", "518880.SH", "513100.SH", "159915.SZ"]
    codes_str = ",".join(f"'{c}'" for c in codes)
    sql = f"""
    SELECT code, trade_date, close
    FROM etf_daily
    WHERE code IN ({codes_str})
      AND trade_date >= '2025-04-14'
    ORDER BY trade_date
    """
    with pg_engine.connect() as conn:
        df = pd.read_sql(text(sql), conn)
    if df.empty:
        pytest.skip("ETF price matrix 无数据")
    pivot = df.pivot(index="trade_date", columns="code", values="close")
    pivot.index = pd.to_datetime(pivot.index)
    pivot.sort_index(inplace=True)
    pivot = pivot.dropna(axis=1, how="all")
    return pivot


@pytest.fixture(scope="session")
def real_stock_cross_section(pg_engine) -> dict:
    """5 只股票的截面数据 — 风险归因用

    返回 dict: prices, market_caps, industries, pb_ratios
    """
    codes = ["000001", "600519", "000858", "600036", "300750"]
    codes_str = ",".join(f"'{c}'" for c in codes)
    sql_prices = f"""
    SELECT code, trade_date, close
    FROM stock_daily
    WHERE code IN ({codes_str}) AND trade_date >= '2025-06-01'
    ORDER BY trade_date
    """
    sql_meta = f"""
    SELECT code, market_cap, industry, pb
    FROM stocks
    WHERE code IN ({codes_str})
    """
    with pg_engine.connect() as conn:
        df_prices = pd.read_sql(text(sql_prices), conn)
        df_meta = pd.read_sql(text(sql_meta), conn)

    if df_prices.empty:
        pytest.skip("stock_daily 截面数据不足")

    df_prices["trade_date"] = pd.to_datetime(df_prices["trade_date"])
    prices = df_prices.pivot(index="trade_date", columns="code", values="close")
    prices.sort_index(inplace=True)
    prices = prices.dropna(axis=1, how="all")

    meta = df_meta.set_index("code")
    market_caps = meta["market_cap"].reindex(prices.columns).fillna(100.0).astype(float)
    industries = meta["industry"].reindex(prices.columns).fillna("其他")
    pb_ratios = meta["pb"].reindex(prices.columns).fillna(1.0).astype(float)

    return {
        "prices": prices,
        "market_caps": market_caps,
        "industries": industries,
        "pb_ratios": pb_ratios,
    }
