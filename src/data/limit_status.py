"""涨跌停 / 停牌状态标注

从 stock_daily 表现有数据计算涨跌停状态:
- 涨停: close == high 且涨幅 >= 阈值 - 0.01
- 跌停: close == low 且跌幅 >= 阈值 + 0.01
- 一字板: open == close == high == low
- 停牌: volume == 0

涨跌停阈值:
- 主板: 10%
- 科创板 (688*): 20%
- 创业板 (300*): 20%
- ST: 5%
"""
import pandas as pd
from datetime import date
from typing import Optional

from sqlalchemy import text

from src.common.db import get_session
from src.common.logger import get_logger

logger = get_logger(__name__)


def _get_limit_threshold(code: str) -> float:
    """根据股票代码前缀判断涨跌停阈值"""
    if code.startswith("688") or code.startswith("300"):
        return 20.0
    return 10.0


def get_prior_surge_min_pct(code: str, base_pct: float, *, use_board: bool = True) -> float:
    """按板块涨跌幅动态计算 prior_surge 阈值 (初筛偏松: 主板约 6%, 创/科约 8%)."""
    if not use_board:
        return base_pct
    limit = _get_limit_threshold(code)
    ratio = 0.6 if limit <= 10.0 else 0.4
    return max(base_pct, limit * ratio)


def passes_tradability_filter(
    row: dict,
    *,
    exclude_limit_up: bool = False,
) -> bool:
    """初筛可交易性: 硬排除停牌、一字板、跌停; 涨停默认保留."""
    if row.get("is_suspended"):
        return False
    if row.get("is_one_word_limit"):
        return False
    if row.get("is_limit_down"):
        return False
    if exclude_limit_up and row.get("is_limit_up"):
        return False
    return True


def calc_limit_status(
    trade_date: date,
    codes: Optional[list] = None,
) -> pd.DataFrame:
    """计算指定日期的涨跌停/停牌状态

    Returns:
        DataFrame with columns:
            code, trade_date, is_limit_up, is_limit_down,
            is_one_word_limit, is_suspended, limit_threshold
    """
    with get_session() as session:
        params: dict = {"td": trade_date}
        code_filter = ""
        if codes:
            code_filter = "AND code = ANY(:codes)"
            params["codes"] = codes

        sql = text(f"""
            SELECT code, trade_date, open, high, low, close,
                   pre_close, volume, change_pct
            FROM stock_daily
            WHERE trade_date = :td {code_filter}
        """)
        rows = session.execute(sql, params).fetchall()

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=[
        "code", "trade_date", "open", "high", "low", "close",
        "pre_close", "volume", "change_pct",
    ])

    df["limit_threshold"] = df["code"].apply(_get_limit_threshold)
    df["is_suspended"] = (df["volume"] == 0) | df["volume"].isna()

    df["is_limit_up"] = (
        (df["close"] >= df["high"] - 0.001)
        & (df["change_pct"] >= df["limit_threshold"] - 1.0)
        & ~df["is_suspended"]
    )

    df["is_limit_down"] = (
        (df["close"] <= df["low"] + 0.001)
        & (df["change_pct"] <= -df["limit_threshold"] + 1.0)
        & ~df["is_suspended"]
    )

    df["is_one_word_limit"] = (
        (df["open"] == df["close"])
        & (df["high"] == df["low"])
        & (df["open"] == df["high"])
        & ~df["is_suspended"]
    )

    return df[["code", "trade_date", "is_limit_up", "is_limit_down",
               "is_one_word_limit", "is_suspended", "limit_threshold"]]


def can_buy(code: str, trade_date: date) -> bool:
    """判断指定股票在指定日期是否可买入

    涨停板不可买入 (除非开板), 停牌不可买入
    """
    df = calc_limit_status(trade_date, [code])
    if df.empty:
        return False
    row = df.iloc[0]
    if row["is_suspended"]:
        return False
    if row["is_one_word_limit"] and row["is_limit_up"]:
        return False
    return True


def can_sell(code: str, trade_date: date) -> bool:
    """判断指定股票在指定日期是否可卖出

    跌停板不可卖出, 停牌不可卖出
    """
    df = calc_limit_status(trade_date, [code])
    if df.empty:
        return False
    row = df.iloc[0]
    if row["is_suspended"]:
        return False
    if row["is_one_word_limit"] and row["is_limit_down"]:
        return False
    return True
