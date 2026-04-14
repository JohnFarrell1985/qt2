"""ETF Rotation E2E — conftest

直连生产 PostgreSQL (public schema), 使用真实 etf_daily 数据。
所有测试均为 read-only, 不写入任何数据。
"""
import pytest
import pandas as pd
from sqlalchemy import create_engine, text

from src.common.config import settings

ETF_RISK_CODES = [
    "510300.SH", "159915.SZ", "510500.SH", "510880.SH",
    "513180.SH", "513100.SH", "513500.SH", "513880.SH",
    "513030.SH", "518880.SH", "159985.SZ",
]
ETF_CANARY_CODES = ["513100.SH"]
ETF_ALL_CODES = list(set(ETF_RISK_CODES + ETF_CANARY_CODES))


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
def real_etf_prices(pg_engine) -> pd.DataFrame:
    """加载所有轮动池 ETF 最近一年的收盘价矩阵

    Returns:
        DataFrame — index=trade_date (datetime), columns=code, values=close
    """
    codes_str = ",".join(f"'{c}'" for c in ETF_ALL_CODES)
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
        pytest.skip("etf_daily 无数据")
    pivot = df.pivot(index="trade_date", columns="code", values="close")
    pivot.index = pd.to_datetime(pivot.index)
    pivot.sort_index(inplace=True)
    return pivot


@pytest.fixture(scope="session")
def real_etf_ohlcv(pg_engine) -> pd.DataFrame:
    """加载 510300.SH 的完整 OHLCV 日线"""
    sql = """
    SELECT code, trade_date, open, high, low, close, volume
    FROM etf_daily
    WHERE code = '510300.SH' AND trade_date >= '2025-04-14'
    ORDER BY trade_date
    """
    with pg_engine.connect() as conn:
        df = pd.read_sql(text(sql), conn)
    if df.empty:
        pytest.skip("510300.SH 无数据")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


@pytest.fixture(scope="session")
def real_multi_etf_ohlcv(pg_engine) -> pd.DataFrame:
    """加载多只 ETF 的完整 OHLCV 日线 (用于组合优化)"""
    codes = ["510300.SH", "510500.SH", "518880.SH", "513100.SH", "159915.SZ"]
    codes_str = ",".join(f"'{c}'" for c in codes)
    sql = f"""
    SELECT code, trade_date, open, high, low, close, volume
    FROM etf_daily
    WHERE code IN ({codes_str})
      AND trade_date >= '2025-04-14'
    ORDER BY trade_date
    """
    with pg_engine.connect() as conn:
        df = pd.read_sql(text(sql), conn)
    if df.empty:
        pytest.skip("多 ETF 无数据")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df
