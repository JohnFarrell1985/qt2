"""Compare filter funnel between bull_launch and bear_rebound."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.common.config import apply_strategy, settings
from src.selection.ma_screener import (
    compute_mas,
    passes_ma_filter,
    passes_max_total_gain_filter,
    passes_prior_surge_filter,
    passes_volume_pullback_filter,
    _load_bars_from_db,
    _load_universe,
)
from scripts.run_screen_audit import _lookback_bars


def analyze(strategy_id: str, trade_date: date) -> None:
    apply_strategy(strategy_id)
    cfg = settings.selection.ma_filter
    max_period = max(cfg.compute_periods)
    lookback = _lookback_bars()
    universe = _load_universe(trade_date, cfg)

    cum = {"ma": 0, "surge": 0, "gain": 0, "vol": 0}
    prox_only_fail = 0
    bull_overlap = 0

    for code in universe:
        bars = _load_bars_from_db(code, trade_date, lookback)
        if bars is None or len(bars) < max_period + 1:
            continue
        mas = compute_mas(bars["close"].astype(float), cfg.compute_periods)
        ok_ma = passes_ma_filter(mas, cfg)
        ok_surge = passes_prior_surge_filter(bars, cfg)
        ok_gain = passes_max_total_gain_filter(bars, cfg)
        ok_vol = passes_volume_pullback_filter(bars, mas, cfg)

        if ok_ma:
            cum["ma"] += 1
        if ok_ma and ok_surge:
            cum["surge"] += 1
        if ok_ma and ok_surge and ok_gain:
            cum["gain"] += 1
        if ok_ma and ok_surge and ok_gain and ok_vol:
            cum["vol"] += 1

        if ok_ma and ok_surge and ok_gain and not ok_vol:
            cfg_no_prox = cfg.model_copy()
            cfg_no_prox.require_ma5_proximity = False
            if passes_volume_pullback_filter(bars, mas, cfg_no_prox):
                prox_only_fail += 1

    print(f"=== {strategy_id} ===")
    print(f"  filter_periods={cfg.filter_periods}")
    print(f"  anchor=MA{cfg.anchor_ma_period} prox=±{cfg.ma5_proximity_pct}%")
    print(f"  surge={cfg.prior_surge_lookback_days}d >{cfg.prior_surge_min_pct}%")
    print(f"  max_gain {cfg.max_gain_lookback_days}d <= {cfg.max_gain_total_pct}%")
    print(f"  funnel: ma={cum['ma']} -> +surge={cum['surge']} -> +gain={cum['gain']} -> +vol={cum['vol']}")
    print(f"  pass ma+surge+gain but fail ONLY anchor proximity: {prox_only_fail}")


def compare_overlap(trade_date: date) -> None:
    """Stocks passing bull but not bear and vice versa."""
    results: dict[str, set[str]] = {}
    for sid in ("bull_launch", "bear_rebound"):
        apply_strategy(sid)
        cfg = settings.selection.ma_filter
        max_period = max(cfg.compute_periods)
        lookback = _lookback_bars()
        universe = _load_universe(trade_date, cfg)
        passed: set[str] = set()
        for code in universe:
            bars = _load_bars_from_db(code, trade_date, lookback)
            if bars is None or len(bars) < max_period + 1:
                continue
            mas = compute_mas(bars["close"].astype(float), cfg.compute_periods)
            if not passes_ma_filter(mas, cfg):
                continue
            if not passes_prior_surge_filter(bars, cfg):
                continue
            if not passes_max_total_gain_filter(bars, cfg):
                continue
            if not passes_volume_pullback_filter(bars, mas, cfg):
                continue
            passed.add(code)
        results[sid] = passed

    bull, bear = results["bull_launch"], results["bear_rebound"]
    print("\n=== overlap ===")
    print(f"  bull only: {len(bull - bear)}")
    print(f"  bear only: {len(bear - bull)}")
    print(f"  both: {len(bull & bear)}")


if __name__ == "__main__":
    td = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date(2026, 3, 11)
    for s in ("bull_launch", "bear_rebound"):
        analyze(s, td)
    compare_overlap(td)
