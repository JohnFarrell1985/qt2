"""Backtest E2E — conftest

直连生产 PostgreSQL (public schema), 使用真实 stock_daily 数据。
回测测试为 read-only（仅读取行情数据），不写入任何数据。
"""
import pytest
import pandas as pd
from datetime import date
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
def real_trading_calendar(pg_engine) -> list[date]:
    """最近 60 个交易日日历"""
    sql = """
    SELECT DISTINCT trade_date FROM stock_daily
    WHERE trade_date >= '2025-10-01'
    ORDER BY trade_date
    LIMIT 60
    """
    with pg_engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()
    if len(rows) < 20:
        pytest.skip("stock_daily 交易日历数据不足 20 天")
    return [r[0] for r in rows]


@pytest.fixture(scope="session")
def real_ohlcv_sample(pg_engine) -> pd.DataFrame:
    """5 只股票最近 60 个交易日的完整 OHLCV"""
    sql = """
    SELECT code, trade_date, open, high, low, close,
           pre_close, volume, amount, change_pct
    FROM stock_daily
    WHERE code IN ('000001', '600519', '000858', '600036', '300750')
      AND trade_date >= '2025-10-01'
    ORDER BY trade_date, code
    """
    with pg_engine.connect() as conn:
        df = pd.read_sql(text(sql), conn)
    if df.empty or len(df) < 100:
        pytest.skip("stock_daily OHLCV 数据不足")
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
    return df


@pytest.fixture(scope="session")
def backtest_date_range(real_trading_calendar) -> tuple[date, date]:
    """回测日期区间: 取日历中间 20 天"""
    mid = len(real_trading_calendar) // 2
    start = real_trading_calendar[max(0, mid - 10)]
    end = real_trading_calendar[min(len(real_trading_calendar) - 1, mid + 10)]
    return start, end
