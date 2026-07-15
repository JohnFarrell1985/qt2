"""K 线前复权口径校正 (选股 / 回测 / 行情读取共用).

**原则**: 库内 ``stock_daily`` 应存前复权 (qfq) 价; 增量同步在除权后若未全量刷新,
会出现「历史旧价 + 除权日新价」混用。本模块提供:

1. ``repair_mixed_adjustment_bars`` — 读取时兜底校正 (所有策略经 ``ma_screener`` 加载 K 线时生效)
2. ``detect_ex_dividend_gap_index`` — 检测除权跳变位置 (供同步层触发全量刷新)
"""
from __future__ import annotations

import pandas as pd

from src.common.logger import get_logger

logger = get_logger(__name__)

# 相邻交易日收盘跳变超过此阈值 (%), 且 change_pct 不一致时, 视为除权除息
EX_DIV_GAP_PCT = 12.0
EX_DIV_CHG_TOLERANCE = 3.0
EX_DIV_FACTOR_MIN = 0.5
EX_DIV_FACTOR_MAX = 0.98


def detect_ex_dividend_gap_index(bars: pd.DataFrame) -> int | None:
    """返回除权日所在行索引 (0-based); 无跳变返回 ``None``."""
    if len(bars) < 2 or "close" not in bars.columns:
        return None
    close = bars["close"].astype(float)
    for i in range(len(bars) - 1, 0, -1):
        prev_c = float(close.iloc[i - 1])
        cur_c = float(close.iloc[i])
        if prev_c <= 0 or cur_c <= 0:
            continue
        day_pct = (cur_c / prev_c - 1) * 100
        if abs(day_pct) < EX_DIV_GAP_PCT:
            continue
        chg = bars["change_pct"].iloc[i] if "change_pct" in bars.columns else None
        if chg is not None and not pd.isna(chg) and abs(float(chg) - day_pct) < EX_DIV_CHG_TOLERANCE:
            continue
        factor = cur_c / prev_c
        if EX_DIV_FACTOR_MIN <= factor <= EX_DIV_FACTOR_MAX:
            return i
    return None


def repair_mixed_adjustment_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """将混用未复权历史 + 除权日复权现价, 缩放为统一前复权口径."""
    if len(bars) < 2:
        return bars
    gap_i = detect_ex_dividend_gap_index(bars)
    if gap_i is None:
        return bars

    out = bars.copy()
    price_cols = [c for c in ("open", "high", "low", "close") if c in out.columns]
    if not price_cols:
        return out

    prev_c = float(out["close"].iloc[gap_i - 1])
    cur_c = float(out["close"].iloc[gap_i])
    factor = cur_c / prev_c
    for col in price_cols:
        out.iloc[:gap_i, out.columns.get_loc(col)] = (
            out.iloc[:gap_i][col].astype(float) * factor
        )
    return out
