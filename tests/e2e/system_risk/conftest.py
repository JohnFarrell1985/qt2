"""P11 System Risk E2E — conftest

直连生产 PostgreSQL (public schema), 使用真实数据, 不做 seed / teardown。
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
def real_stock_codes(pg_engine) -> list[str]:
    """从 stocks 表取一批覆盖各板块的真实股票代码"""
    sql = """
    SELECT code FROM stocks
    WHERE code IN (
        '000001', '600519', '688001', '300750',
        '301696', '920012', '000858', '600036'
    )
    ORDER BY code
    """
    with pg_engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()
    return [r[0] for r in rows]


@pytest.fixture(scope="session")
def real_stock_daily_df(pg_engine) -> pd.DataFrame:
    """平安银行 000001 最近两年的日线 — 足够做 CV / factor / regime 测试"""
    sql = """
    SELECT code, trade_date, open, high, low, close, volume, change_pct
    FROM stock_daily
    WHERE code = '000001' AND trade_date >= '2024-01-01'
    ORDER BY trade_date
    """
    with pg_engine.connect() as conn:
        df = pd.read_sql(text(sql), conn)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


@pytest.fixture(scope="session")
def real_multi_stock_daily(pg_engine) -> pd.DataFrame:
    """多只股票近一年日线 — 用于截面 IC / factor 测试"""
    sql = """
    SELECT code, trade_date, close, volume, change_pct
    FROM stock_daily
    WHERE code IN ('000001', '600519', '000858', '600036', '300750')
      AND trade_date >= '2025-01-01'
    ORDER BY trade_date, code
    """
    with pg_engine.connect() as conn:
        df = pd.read_sql(text(sql), conn)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df


@pytest.fixture(scope="session")
def real_index_prices(pg_engine) -> pd.Series:
    """沪深300近两年收盘价序列 — RegimeGate 用"""
    sql = """
    SELECT trade_date, close
    FROM market_index
    WHERE index_code = '000300' AND trade_date >= '2024-01-01'
    ORDER BY trade_date
    """
    with pg_engine.connect() as conn:
        df = pd.read_sql(text(sql), conn)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    return df.set_index("trade_date")["close"]


@pytest.fixture(scope="session")
def real_etf_daily_df(pg_engine) -> pd.DataFrame:
    """上证50 ETF (510050) 最近一年的日线"""
    sql = """
    SELECT code, trade_date, open, high, low, close, volume
    FROM etf_daily
    WHERE code LIKE '510050%' AND trade_date >= '2025-01-01'
    ORDER BY trade_date
    """
    with pg_engine.connect() as conn:
        df = pd.read_sql(text(sql), conn)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["code"] = df["code"].str.replace(r"\.SH$", "", regex=True)
    return df


@pytest.fixture(scope="session")
def real_cross_border_etf_df(pg_engine) -> pd.DataFrame:
    """跨境 ETF (513xxx) 最近半年日线"""
    sql = """
    SELECT code, trade_date, open, high, low, close, volume
    FROM etf_daily
    WHERE code LIKE '513050%' AND trade_date >= '2025-06-01'
    ORDER BY trade_date
    """
    with pg_engine.connect() as conn:
        df = pd.read_sql(text(sql), conn)
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df["code"] = df["code"].str.replace(r"\.SH$", "", regex=True)
    return df


@pytest.fixture(scope="session")
def all_stock_codes_sample(pg_engine) -> list[str]:
    """从所有板块各取几只, 供 trading rules 覆盖测试"""
    sql = """
    (SELECT code FROM stocks WHERE code LIKE '6%' AND LENGTH(code)=6 LIMIT 3)
    UNION ALL
    (SELECT code FROM stocks WHERE code LIKE '000%' AND LENGTH(code)=6 LIMIT 3)
    UNION ALL
    (SELECT code FROM stocks WHERE code LIKE '688%' AND LENGTH(code)=6 LIMIT 3)
    UNION ALL
    (SELECT code FROM stocks WHERE code LIKE '300%' AND LENGTH(code)=6 LIMIT 3)
    UNION ALL
    (SELECT code FROM stocks WHERE code LIKE '301%' AND LENGTH(code)=6 LIMIT 2)
    UNION ALL
    (SELECT code FROM stocks WHERE code LIKE '8%' AND LENGTH(code)=6 LIMIT 2)
    """
    with pg_engine.connect() as conn:
        rows = conn.execute(text(sql)).fetchall()
    return [r[0] for r in rows]
