"""Pandera 数据质量 Schema 定义

为 stock_daily、ETF、可转债等数据定义校验规则。
分层校验：Schema 层 → 业务规则层 → 统计层。

Reference: https://pandera.readthedocs.io/
"""
from pandera.pandas import Column, Check, DataFrameSchema

stock_daily_schema = DataFrameSchema(
    {
        "code": Column(str, Check.str_matches(r"^\d{6}")),
        "trade_date": Column("datetime64[ns]", nullable=False),
        "open": Column(float, Check.gt(0)),
        "high": Column(float, Check.gt(0)),
        "low": Column(float, Check.gt(0)),
        "close": Column(float, Check.gt(0)),
        "volume": Column(float, Check.ge(0)),
    },
    checks=[
        Check(lambda df: (df["high"] >= df["low"]).all(), error="high < low"),
        Check(lambda df: (df["high"] >= df["open"]).all(), error="high < open"),
        Check(lambda df: (df["high"] >= df["close"]).all(), error="high < close"),
        Check(lambda df: (df["low"] <= df["open"]).all(), error="low > open"),
        Check(lambda df: (df["low"] <= df["close"]).all(), error="low > close"),
    ],
)

etf_daily_schema = DataFrameSchema(
    {
        "code": Column(str, Check.str_matches(r"^\d{6}")),
        "trade_date": Column("datetime64[ns]", nullable=False),
        "open": Column(float, Check.gt(0)),
        "high": Column(float, Check.gt(0)),
        "low": Column(float, Check.gt(0)),
        "close": Column(float, Check.gt(0)),
        "volume": Column(float, Check.ge(0)),
    },
    checks=[
        Check(lambda df: (df["high"] >= df["low"]).all(), error="high < low"),
        Check(lambda df: (df["high"] >= df["open"]).all(), error="high < open"),
        Check(lambda df: (df["high"] >= df["close"]).all(), error="high < close"),
        Check(lambda df: (df["low"] <= df["open"]).all(), error="low > open"),
        Check(lambda df: (df["low"] <= df["close"]).all(), error="low > close"),
    ],
)

cb_data_schema = DataFrameSchema(
    {
        "code": Column(str, Check.str_matches(r"^\d{6}")),
        "trade_date": Column("datetime64[ns]", nullable=False),
        "close": Column(float, Check.gt(0)),
        "volume": Column(float, Check.ge(0)),
    },
)

SCHEMA_REGISTRY: dict[str, DataFrameSchema] = {
    "stock_daily": stock_daily_schema,
    "etf_daily": etf_daily_schema,
    "cb_data": cb_data_schema,
}
