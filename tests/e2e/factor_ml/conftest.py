"""Factor ML E2E — conftest

直连生产 PostgreSQL (public schema), 使用真实 stock_daily 数据。
所有测试均为 read-only, 不写入任何数据。
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
def real_single_stock_ohlcv(pg_engine) -> pd.DataFrame:
    """平安银行 000001 最近一年 OHLCV — Alpha158 单股计算"""
    sql = """
    SELECT code, trade_date, open, high, low, close, volume
    FROM stock_daily
    WHERE code = '000001' AND trade_date >= '2025-01-01'
    ORDER BY trade_date
    """
    with pg_engine.connect() as conn:
        df = pd.read_sql(text(sql), conn)
    if df.empty:
        pytest.skip("000001 stock_daily 无数据")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


@pytest.fixture(scope="session")
def real_multi_stock_panel(pg_engine) -> pd.DataFrame:
    """多只股票面板数据 — AutoScreen / QualityGate 用"""
    sql = """
    SELECT code, trade_date, open, high, low, close, volume, change_pct
    FROM stock_daily
    WHERE code IN ('000001', '600519', '000858', '600036', '300750')
      AND trade_date >= '2025-01-01'
    ORDER BY trade_date, code
    """
    with pg_engine.connect() as conn:
        df = pd.read_sql(text(sql), conn)
    if df.empty or len(df) < 500:
        pytest.skip("多股票 stock_daily 数据不足")
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df
