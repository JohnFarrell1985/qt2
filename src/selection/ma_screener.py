"""均线计算与向上发散 + 缩量回调初筛.

本模块中「当天 / 前一日 / 前 N 日」均指 **交易日** (``stock_daily`` 连续 K 线),
不含周末与节假日, 不做自然日 ``timedelta`` 换算.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
from sqlalchemy import text

from src.common.config import MaFilterConfig, RankConfig, settings
from src.common.db import get_session
from src.common.logger import get_logger
from src.data.limit_status import calc_limit_status, get_prior_surge_min_pct, passes_tradability_filter
from src.data.universe_provider import AStockUniverseProvider

logger = get_logger(__name__)

DEFAULT_COMPUTE_PERIODS = [5, 10, 15, 20, 30, 40, 50, 60]


def compute_mas(closes: pd.Series, periods: list[int]) -> dict[int, pd.Series]:
    """对收盘价序列计算多条移动平均线."""
    return {p: closes.rolling(p).mean() for p in periods}


def _latest(series: pd.Series, offset: int = 0) -> float | None:
    idx = -(1 + offset)
    if len(series) < abs(idx):
        return None
    val = series.iloc[idx]
    if pd.isna(val):
        return None
    return float(val)


def _divergence_at_offset(
    mas: dict[int, pd.Series],
    cfg: MaFilterConfig,
    offset: int,
) -> bool:
    """指定交易日是否满足向上发散 (相对前一日)."""
    periods = cfg.filter_periods
    for p in periods:
        if p not in mas:
            return False
        if _latest(mas[p], offset) is None or _latest(mas[p], offset + 1) is None:
            return False

    if cfg.require_bullish_order:
        for i in range(len(periods) - 1):
            short_p, long_p = periods[i], periods[i + 1]
            if _latest(mas[short_p], offset) <= _latest(mas[long_p], offset):
                return False

    if cfg.require_rising:
        for p in periods:
            if _latest(mas[p], offset) <= _latest(mas[p], offset + 1):
                return False

    if cfg.require_spreading:
        for i in range(len(periods) - 1):
            short_p, long_p = periods[i], periods[i + 1]
            spread = _latest(mas[short_p], offset) - _latest(mas[long_p], offset)
            prev_spread = _latest(mas[short_p], offset + 1) - _latest(mas[long_p], offset + 1)
            if spread is None or prev_spread is None or spread <= prev_spread:
                return False

    return True


def passes_ma_filter(mas: dict[int, pd.Series], cfg: MaFilterConfig) -> bool:
    """筛选日 (最近一根 K 线) 是否向上发散."""
    periods = cfg.filter_periods
    if len(periods) < 2:
        return False
    for p in periods:
        if p not in mas:
            return False
    return _divergence_at_offset(mas, cfg, offset=0)


def _daily_change_pct(bars: pd.DataFrame, bar_index: int) -> float | None:
    """单日涨跌幅 (%), ``bar_index`` 为 bars 中的位置."""
    if bar_index < 1 or bar_index >= len(bars):
        return None
    if "change_pct" in bars.columns:
        val = bars["change_pct"].iloc[bar_index]
        if pd.notna(val):
            return float(val)
    prev = float(bars["close"].iloc[bar_index - 1])
    cur = float(bars["close"].iloc[bar_index])
    if prev <= 0:
        return None
    return (cur / prev - 1) * 100


def _effective_prior_surge_min_pct(code: str, cfg: MaFilterConfig) -> float:
    return get_prior_surge_min_pct(
        code,
        cfg.prior_surge_min_pct,
        use_board=cfg.prior_surge_use_board_threshold,
    )


def passes_prior_surge_filter(
    bars: pd.DataFrame,
    cfg: MaFilterConfig,
    code: str = "",
) -> bool:
    """筛选日之前的 N 个交易日内, 是否出现过单日大涨."""
    lookback = cfg.prior_surge_lookback_days
    if len(bars) < lookback + 2:
        return False
    threshold = _effective_prior_surge_min_pct(code, cfg) if code else cfg.prior_surge_min_pct
    last_idx = len(bars) - 1
    for offset in range(1, lookback + 1):
        idx = last_idx - offset
        pct = _daily_change_pct(bars, idx)
        if pct is not None and pct > threshold:
            return True
    return False


def total_gain_pct(bars: pd.DataFrame, lookback_days: int) -> float | None:
    """近 ``lookback_days`` 个交易日累计涨幅 (%): 今日收盘 / N 个交易日前收盘."""
    if len(bars) < lookback_days + 1:
        return None
    close = bars["close"].astype(float)
    base = close.iloc[-(lookback_days + 1)]
    end = close.iloc[-1]
    if pd.isna(base) or pd.isna(end) or base <= 0:
        return None
    return (end / base - 1) * 100


def passes_max_total_gain_filter(bars: pd.DataFrame, cfg: MaFilterConfig) -> bool:
    """近 N 个交易日总涨幅不超过上限."""
    pct = total_gain_pct(bars, cfg.max_gain_lookback_days)
    if pct is None:
        return False
    return pct <= cfg.max_gain_total_pct


def passes_volume_pullback_filter(
    bars: pd.DataFrame,
    mas: dict[int, pd.Series],
    cfg: MaFilterConfig,
) -> bool:
    """筛选日相对上一交易日缩量; 可选贴近锚点均线、不破均线."""
    if not cfg.require_volume_pullback:
        return True

    if len(bars) < 2:
        return False

    volume = bars["volume"].astype(float)
    v_today = volume.iloc[-1]
    v_yday = volume.iloc[-2]
    if pd.isna(v_today) or pd.isna(v_yday) or v_yday <= 0:
        return False
    if v_today >= v_yday * cfg.volume_shrink_ratio:
        return False

    if not cfg.require_ma5_proximity:
        return True

    anchor = cfg.anchor_ma_period
    if anchor not in mas:
        return False

    close = bars["close"].astype(float)
    low = bars["low"].astype(float)
    ma_anchor = mas[anchor].astype(float)
    c = close.iloc[-1]
    l = low.iloc[-1]
    ma_val = ma_anchor.iloc[-1]
    if any(pd.isna(x) for x in (ma_val, c, l)) or ma_val <= 0:
        return False
    if cfg.require_low_above_ma5 and l < ma_val:
        return False
    if abs(c - ma_val) / ma_val * 100 > cfg.ma5_proximity_pct:
        return False
    return True


def _max_prior_surge_pct(bars: pd.DataFrame, cfg: MaFilterConfig, code: str = "") -> float | None:
    lookback = cfg.prior_surge_lookback_days
    threshold = _effective_prior_surge_min_pct(code, cfg) if code else cfg.prior_surge_min_pct
    last_idx = len(bars) - 1
    best: float | None = None
    for offset in range(1, lookback + 1):
        pct = _daily_change_pct(bars, last_idx - offset)
        if pct is not None and pct > threshold and (best is None or pct > best):
            best = pct
    return best


def _days_since_surge(bars: pd.DataFrame, cfg: MaFilterConfig, code: str = "") -> int | None:
    """距筛选日最近的大涨发生在几个交易日前 (1=上一交易日)."""
    lookback = cfg.prior_surge_lookback_days
    threshold = _effective_prior_surge_min_pct(code, cfg) if code else cfg.prior_surge_min_pct
    last_idx = len(bars) - 1
    nearest: int | None = None
    for offset in range(1, lookback + 1):
        idx = last_idx - offset
        pct = _daily_change_pct(bars, idx)
        if pct is not None and pct > threshold:
            if nearest is None or offset < nearest:
                nearest = offset
    return nearest


def _score_linear_low_better(value: float, best: float, worst: float) -> float:
    if value <= best:
        return 100.0
    if value >= worst:
        return 0.0
    return 100.0 * (worst - value) / (worst - best)


def _score_gain_10d(gain: float | None) -> float:
    """8～18% 区间最佳, 接近 30% 上限降分."""
    if gain is None:
        return 50.0
    if 8.0 <= gain <= 18.0:
        return max(70.0, 100.0 - abs(gain - 13.0) * 3.0)
    if gain < 8.0:
        return max(0.0, 100.0 - (8.0 - gain) * 8.0)
    return max(0.0, 100.0 - (gain - 18.0) * 6.0)


def _score_surge_recency(days: int | None, lookback: int) -> float:
    if days is None:
        return 50.0
    if days <= 1:
        return 100.0
    if days >= lookback:
        return 20.0
    return 100.0 - (days - 1) * (80.0 / max(lookback - 1, 1))


def _score_liquidity(
    avg_turnover: float | None,
    avg_amount: float | None = None,
) -> float:
    """20 日均换手率优先; 缺失时回退到成交额."""
    if avg_turnover is not None and avg_turnover > 0:
        if 3.0 <= avg_turnover <= 8.0:
            return max(70.0, 100.0 - abs(avg_turnover - 5.5) * 5.0)
        if avg_turnover < 1.5:
            return max(0.0, 100.0 * avg_turnover / 1.5)
        if avg_turnover > 8.0:
            return max(40.0, 100.0 - (avg_turnover - 8.0) * 5.0)
        return 50.0 + (avg_turnover - 1.5) * (20.0 / 1.5)

    if avg_amount is None or avg_amount <= 0:
        return 50.0
    wan = avg_amount / 10_000.0
    if wan >= 5000:
        return 100.0
    if wan <= 1000:
        return 0.0
    return 100.0 * (wan - 1000) / 4000.0


def _score_limit_up_penalty(is_limit_up: bool) -> float:
    """涨停收盘降权但不剔除 (初筛供人工复核)."""
    return 60.0 if is_limit_up else 100.0


def assign_tier(score: float, rank_cfg: RankConfig) -> str:
    if score >= rank_cfg.tier_a_min:
        return "A"
    if score >= rank_cfg.tier_b_min:
        return "B"
    return "C"


def score_snapshot(
    snap: dict[str, float],
    rank_cfg: RankConfig,
    cfg: MaFilterConfig,
    avg_turnover_20d: float | None = None,
    avg_amount_20d: float | None = None,
    is_limit_up: bool = False,
) -> float:
    gain_key = f"gain_{cfg.max_gain_lookback_days}d_pct"
    parts = {
        "ma5_dist": _score_linear_low_better(snap.get("ma5_dist_pct", 99.0), 0.0, 5.0),
        "vol_shrink": _score_linear_low_better(snap.get("vol_shrink_ratio", 1.0), 0.5, 1.0),
        "gain_10d": _score_gain_10d(snap.get(gain_key)),
        "surge_recency": _score_surge_recency(
            int(snap["days_since_surge"]) if snap.get("days_since_surge") is not None else None,
            cfg.prior_surge_lookback_days,
        ),
        "liquidity": _score_liquidity(avg_turnover_20d, avg_amount_20d),
        "tradability": _score_limit_up_penalty(is_limit_up),
    }
    weights = {
        "ma5_dist": rank_cfg.weight_ma5_dist,
        "vol_shrink": rank_cfg.weight_vol_shrink,
        "gain_10d": rank_cfg.weight_gain_10d,
        "surge_recency": rank_cfg.weight_surge_recency,
        "liquidity": rank_cfg.weight_liquidity,
        "tradability": rank_cfg.weight_liquidity * 0.5,
    }
    total_w = sum(weights.values()) or 1.0
    return sum(parts[k] * weights[k] for k in parts) / total_w


def screen_metrics(
    bars: pd.DataFrame,
    mas: dict[int, pd.Series],
    cfg: MaFilterConfig,
    periods: list[int],
    code: str = "",
) -> dict[str, float]:
    anchor = cfg.anchor_ma_period
    close = bars["close"].astype(float)
    volume = bars["volume"].astype(float)
    ma_val = float(mas[anchor].iloc[-1])
    c = float(close.iloc[-1])
    v_today = float(volume.iloc[-1])
    v_yday = float(volume.iloc[-2])
    snap: dict[str, float] = {}
    for p in periods:
        val = _latest(mas.get(p, pd.Series(dtype=float)))
        if val is not None:
            snap[f"ma{p}"] = round(val, 4)
    snap.update({
        "close": round(c, 4),
        f"ma{anchor}": round(ma_val, 4),
        "ma5_dist_pct": round(abs(c - ma_val) / ma_val * 100, 4),
        "vol_shrink_ratio": round(v_today / v_yday, 4) if v_yday > 0 else 0.0,
    })
    low = bars["low"].astype(float).iloc[-1]
    if pd.notna(low) and ma_val > 0:
        snap["low_ma5_dist_pct"] = round((float(low) - ma_val) / ma_val * 100, 4)
    ds = _days_since_surge(bars, cfg, code)
    if ds is not None:
        snap["days_since_surge"] = float(ds)
    surge = _max_prior_surge_pct(bars, cfg, code)
    if surge is not None:
        snap["max_prior_surge_pct"] = round(surge, 4)
    gain = total_gain_pct(bars, cfg.max_gain_lookback_days)
    if gain is not None:
        snap[f"gain_{cfg.max_gain_lookback_days}d_pct"] = round(gain, 4)
    return snap


def ma_snapshot(
    bars: pd.DataFrame,
    mas: dict[int, pd.Series],
    periods: list[int],
    cfg: MaFilterConfig,
    code: str = "",
) -> dict[str, float]:
    return screen_metrics(bars, mas, cfg, periods, code)


def _load_universe(trade_date: date, cfg: MaFilterConfig) -> list[str]:
    if cfg.universe_file:
        path = Path(cfg.universe_file)
        if not path.is_absolute():
            from src.common.config import PROJECT_ROOT
            path = PROJECT_ROOT / cfg.universe_file
        codes = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return codes

    if cfg.universe == "all_a":
        provider = AStockUniverseProvider()
        return provider.get_codes(trade_date, exclude_st=cfg.exclude_st, exclude_suspended=True)

    raise ValueError(f"未知 universe 配置: {cfg.universe}")


def _load_bars_from_db(code: str, trade_date: date, lookback: int) -> pd.DataFrame | None:
    sql = text("""
        SELECT trade_date, open, high, low, close, volume, amount, change_pct, turnover_rate
        FROM stock_daily
        WHERE code = :code AND trade_date <= :td
        ORDER BY trade_date DESC
        LIMIT :limit
    """)
    with get_session() as session:
        rows = session.execute(sql, {"code": code, "td": trade_date, "limit": lookback}).fetchall()
    if not rows:
        return None
    df = pd.DataFrame(
        rows,
        columns=["trade_date", "open", "high", "low", "close", "volume", "amount", "change_pct", "turnover_rate"],
    ).sort_values("trade_date")
    for col in ("open", "high", "low", "close", "volume", "amount", "change_pct", "turnover_rate"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _load_bars_from_qmt(code: str, count: int) -> pd.DataFrame | None:
    try:
        from src.data.qmt_client import QMTClient

        client = QMTClient()
        data = client.get_market_data_ex([code], period="1d", count=count, dividend_type="front")
        df = data.get(code)
        if df is None or df.empty:
            return None
        out = df.reset_index().rename(columns={"index": "trade_date"})
        for col in ("open", "high", "low", "close", "volume"):
            if col not in out.columns:
                return None
            out[col] = pd.to_numeric(out[col], errors="coerce")
        out["amount"] = pd.to_numeric(out.get("amount", 0), errors="coerce")
        if "change_pct" not in out.columns and len(out) > 1:
            out["change_pct"] = out["close"].pct_change() * 100
        return out.sort_values("trade_date")
    except Exception as e:
        logger.debug("QMT 拉取 %s 失败: %s", code, e)
        return None


def _fetch_avg_turnover_20d(code: str, trade_date: date) -> float | None:
    sql = text("""
        SELECT AVG(turnover_rate) FROM (
            SELECT turnover_rate FROM stock_daily
            WHERE code = :code AND trade_date <= :td AND turnover_rate IS NOT NULL
            ORDER BY trade_date DESC LIMIT 20
        ) t
    """)
    with get_session() as session:
        row = session.execute(sql, {"code": code, "td": trade_date}).scalar()
    if row is None:
        return None
    return float(row)


def _fetch_avg_amount_20d(code: str, trade_date: date) -> float | None:
    sql = text("""
        SELECT AVG(amount) FROM (
            SELECT amount FROM stock_daily
            WHERE code = :code AND trade_date <= :td
            ORDER BY trade_date DESC LIMIT 20
        ) t
    """)
    with get_session() as session:
        row = session.execute(sql, {"code": code, "td": trade_date}).scalar()
    if row is None:
        return None
    return float(row)


def _passes_liquidity(code: str, trade_date: date, cfg: MaFilterConfig) -> bool:
    """初筛偏松: 20 日均换手率 **或** 成交额任一达标即可; 双缺失则宽进."""
    need_turnover = cfg.min_avg_turnover_20d > 0
    need_amount = cfg.min_avg_amount_20d > 0
    if not need_turnover and not need_amount:
        return True

    avg_to = _fetch_avg_turnover_20d(code, trade_date) if need_turnover else None
    avg_amt = _fetch_avg_amount_20d(code, trade_date) if need_amount or need_turnover else None

    turnover_ok = (
        need_turnover
        and avg_to is not None
        and avg_to >= cfg.min_avg_turnover_20d
    )
    amount_ok = (
        need_amount
        and avg_amt is not None
        and avg_amt >= cfg.min_avg_amount_20d
    )

    if need_turnover and need_amount:
        if turnover_ok or amount_ok:
            return True
        if avg_to is None and avg_amt is None:
            return True
        return False

    if need_turnover:
        if avg_to is None:
            return True
        return avg_to >= cfg.min_avg_turnover_20d

    if avg_amt is None:
        return True
    return avg_amt >= cfg.min_avg_amount_20d


def _load_limit_status_map(trade_date: date) -> dict[str, dict]:
    df = calc_limit_status(trade_date)
    if df.empty:
        return {}
    return df.set_index("code").to_dict("index")


def screen_universe(
    trade_date: date,
    cfg: MaFilterConfig | None = None,
) -> tuple[list[str], dict[str, dict]]:
    """对全市场做 MA 向上发散 + 前期大涨 + 当日缩量初筛."""
    cfg = cfg or settings.selection.ma_filter
    rank_cfg = settings.selection.rank
    max_period = max(cfg.compute_periods)
    lookback = max(
        max_period + cfg.prior_surge_lookback_days + 10,
        cfg.prior_surge_lookback_days + 5,
        cfg.max_gain_lookback_days + 5,
    )

    universe = _load_universe(trade_date, cfg)
    limit_map = _load_limit_status_map(trade_date)
    logger.info("MA 初筛: 日期=%s,  universe=%d 只", trade_date, len(universe))

    candidates: list[str] = []
    snapshots: dict[str, dict] = {}
    scored_rows: list[tuple[str, dict]] = []

    for code in universe:
        bars = _load_bars_from_db(code, trade_date, lookback)
        if bars is None or len(bars) < max_period + 1:
            bars = _load_bars_from_qmt(code, lookback)
        if bars is None or len(bars) < max_period + 1:
            continue

        limit_row = limit_map.get(code)
        if limit_row is not None and not passes_tradability_filter(
            limit_row,
            exclude_limit_up=cfg.exclude_limit_up,
        ):
            continue

        closes = bars["close"].astype(float)
        mas = compute_mas(closes, cfg.compute_periods)
        if not passes_ma_filter(mas, cfg):
            continue
        if not passes_prior_surge_filter(bars, cfg, code):
            continue
        if not passes_max_total_gain_filter(bars, cfg):
            continue
        if not passes_volume_pullback_filter(bars, mas, cfg):
            continue

        if not _passes_liquidity(code, trade_date, cfg):
            continue

        snap = ma_snapshot(bars, mas, cfg.compute_periods, cfg, code)
        if rank_cfg.enabled:
            avg_to = _fetch_avg_turnover_20d(code, trade_date)
            avg_amt = _fetch_avg_amount_20d(code, trade_date)
            is_limit_up = bool(limit_row and limit_row.get("is_limit_up"))
            composite = score_snapshot(
                snap,
                rank_cfg,
                cfg,
                avg_turnover_20d=avg_to,
                avg_amount_20d=avg_amt,
                is_limit_up=is_limit_up,
            )
            snap["composite_score"] = round(composite, 2)
            snap["tier"] = assign_tier(composite, rank_cfg)
            if avg_to is not None:
                snap["avg_turnover_20d"] = round(avg_to, 4)
            if avg_amt is not None:
                snap["avg_amount_20d"] = round(avg_amt, 0)
            if is_limit_up:
                snap["is_limit_up"] = 1.0
        scored_rows.append((code, snap))

    if rank_cfg.enabled:
        scored_rows.sort(key=lambda x: x[1].get("composite_score", 0), reverse=True)
    else:
        scored_rows.sort(key=lambda x: x[0])

    if cfg.max_candidates and len(scored_rows) > cfg.max_candidates:
        scored_rows = scored_rows[: cfg.max_candidates]

    for code, snap in scored_rows:
        candidates.append(code)
        snapshots[code] = snap

    if rank_cfg.enabled and candidates:
        tiers = {t: sum(1 for c in candidates if snapshots[c].get("tier") == t) for t in ("A", "B", "C")}
        logger.info(
            "MA 初筛完成: %d 只 (tier A=%d B=%d C=%d)",
            len(candidates), tiers.get("A", 0), tiers.get("B", 0), tiers.get("C", 0),
        )
    else:
        logger.info("MA 初筛完成: %d 只通过", len(candidates))
    return candidates, snapshots
