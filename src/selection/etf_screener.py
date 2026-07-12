"""场内 ETF 初筛 (松散耦合, 复用 A 股 MA 策略纯函数)

与股票初筛 (``ma_screener.py``) 共享同一套均线 / 前期大涨 / 缩量回调 / 打分逻辑,
但数据来自 ``etf_daily`` (代码为带后缀形式, 如 ``159001.SZ``), 名称取自 ``etf_info``。

ETF 不适用的股票专有过滤 (ST / 涨停可交易性 / 换手率) 一律跳过; 流动性以 20 日均成交额近似。
不修改股票初筛与全局 ``settings``。
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
from sqlalchemy import text

from src.common.config import MaFilterConfig, RankConfig, settings
from src.common.db import get_session
from src.common.logger import get_logger
from src.selection.ma_screener import (
    assign_tier,
    compute_mas,
    ma_snapshot,
    passes_ma_filter,
    passes_ma5_ma10_above_long_filter,
    passes_max_total_gain_filter,
    passes_monthly_gain_filter,
    passes_prior_surge_filter,
    passes_volume_pullback_filter,
    score_snapshot,
)

logger = get_logger(__name__)


def _load_etf_universe(trade_date: date) -> list[str]:
    """截至 trade_date 仍在交易的 ETF 代码 (近 30 自然日内有 K 线)."""
    since = trade_date - timedelta(days=30)
    sql = text(
        "SELECT DISTINCT code FROM etf_daily "
        "WHERE trade_date <= :td AND trade_date >= :since ORDER BY code"
    )
    with get_session(readonly=True) as s:
        rows = s.execute(sql, {"td": trade_date, "since": since}).fetchall()
    return [r[0] for r in rows]


def _load_etf_bars(code: str, trade_date: date, lookback: int) -> pd.DataFrame | None:
    sql = text(
        "SELECT trade_date, open, high, low, close, volume, amount FROM etf_daily "
        "WHERE code = :code AND trade_date <= :td ORDER BY trade_date DESC LIMIT :limit"
    )
    with get_session(readonly=True) as s:
        rows = s.execute(sql, {"code": code, "td": trade_date, "limit": lookback}).fetchall()
    if not rows:
        return None
    df = pd.DataFrame(
        rows, columns=["trade_date", "open", "high", "low", "close", "volume", "amount"]
    ).sort_values("trade_date")
    for col in ("open", "high", "low", "close", "volume", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    # ETF 无 change_pct 列 → 由收盘价推算 (ma_screener._daily_change_pct 亦有兜底)
    df["change_pct"] = df["close"].pct_change() * 100
    df["turnover_rate"] = pd.NA
    return df


def load_etf_names() -> dict[str, str]:
    try:
        with get_session(readonly=True) as s:
            rows = s.execute(text("SELECT code, name FROM etf_info")).fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:  # noqa: BLE001
        return {}


def screen_etf_universe(
    trade_date: date,
    cfg: MaFilterConfig | None = None,
    rank_cfg: RankConfig | None = None,
) -> tuple[list[str], dict[str, dict]]:
    """对场内 ETF 做与股票一致的 MA 初筛 + 打分 (跳过 ST/涨停/换手率)."""
    cfg = cfg or settings.selection.ma_filter
    rank_cfg = rank_cfg or settings.selection.rank
    max_period = max(cfg.compute_periods)
    lookback = max(
        max_period + cfg.prior_surge_lookback_days + 10,
        cfg.max_gain_lookback_days + 5,
        cfg.max_gain_1m_lookback_days + 5,
    )

    universe = _load_etf_universe(trade_date)
    logger.info("ETF 初筛: 日期=%s, universe=%d 只", trade_date, len(universe))

    scored_rows: list[tuple[str, dict]] = []
    skip_no_bars = 0

    for code in universe:
        bars = _load_etf_bars(code, trade_date, lookback)
        if bars is None or len(bars) < max_period + 1:
            skip_no_bars += 1
            continue

        closes = bars["close"].astype(float)
        mas = compute_mas(closes, cfg.compute_periods)
        if not passes_ma_filter(mas, cfg):
            continue
        if not passes_ma5_ma10_above_long_filter(mas, cfg):
            continue
        if not passes_prior_surge_filter(bars, cfg, code):
            continue
        if not passes_max_total_gain_filter(bars, cfg):
            continue
        if not passes_monthly_gain_filter(bars, cfg):
            continue
        if not passes_volume_pullback_filter(bars, mas, cfg):
            continue

        snap = ma_snapshot(bars, mas, cfg.compute_periods, cfg, code)
        if rank_cfg.enabled:
            avg_amt = float(bars["amount"].tail(20).mean()) if len(bars) else None
            composite = score_snapshot(
                snap, rank_cfg, cfg,
                avg_turnover_20d=None,
                avg_amount_20d=avg_amt,
                is_limit_up=False,
            )
            snap["composite_score"] = round(composite, 2)
            snap["tier"] = assign_tier(composite, rank_cfg)
            if avg_amt is not None:
                snap["avg_amount_20d"] = round(avg_amt, 0)
        scored_rows.append((code, snap))

    if rank_cfg.enabled:
        scored_rows.sort(key=lambda x: x[1].get("composite_score", 0), reverse=True)
    else:
        scored_rows.sort(key=lambda x: x[0])

    if cfg.max_candidates and len(scored_rows) > cfg.max_candidates:
        scored_rows = scored_rows[: cfg.max_candidates]

    candidates = [c for c, _ in scored_rows]
    snapshots = {c: snap for c, snap in scored_rows}
    logger.info("ETF 初筛完成: %d 只通过, 跳过无K线=%d", len(candidates), skip_no_bars)
    return candidates, snapshots
