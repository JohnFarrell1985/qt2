"""Compare bull_launch with/without MA5/MA10 cross filter and forward returns."""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from src.common.config import apply_strategy, settings
from src.common.db import get_session
from src.selection.ma_screener import (
    compute_mas,
    detect_ma5_ma10_cross,
    passes_ma_filter,
    passes_max_total_gain_filter,
    passes_prior_surge_filter,
    passes_volume_pullback_filter,
    screen_universe,
    _load_bars_from_db,
    _load_universe,
)
from scripts.run_screen_audit import _lookback_bars


def _screen(td: date, cross_enabled: bool):
    apply_strategy("bull_launch")
    cfg = settings.selection.ma_filter.model_copy(
        update={"require_ma5_ma10_cross": cross_enabled},
    )
    return screen_universe(td, cfg)


def _forward_return(codes: list[str], from_d: date, to_d: date) -> dict[str, float]:
    sql = text("SELECT close FROM stock_daily WHERE code=:c AND trade_date=:d")
    out: dict[str, float] = {}
    with get_session() as session:
        for code in codes:
            c0 = session.execute(sql, {"c": code, "d": from_d}).scalar()
            c1 = session.execute(sql, {"c": code, "d": to_d}).scalar()
            if c0 and c1 and float(c0) > 0:
                out[code] = (float(c1) / float(c0) - 1) * 100
    return out


def main() -> None:
    td = date(2026, 7, 9)
    old_codes, _ = _screen(td, False)
    new_codes, new_snaps = _screen(td, True)

    print("=== candidate compare 2026-07-09 ===")
    print(f"old (no cross filter): {len(old_codes)}")
    print(f"new (with cross):      {len(new_codes)}")
    print(f"added:  {sorted(set(new_codes) - set(old_codes)) or 'none'}")
    print(f"removed:{sorted(set(old_codes) - set(new_codes)) or 'none'}")

    states = Counter(s.get("ma5_ma10_cross_state") for s in new_snaps.values())
    print(f"cross states: {dict(states)}")

    apply_strategy("bull_launch")
    cfg = settings.selection.ma_filter
    lookback = _lookback_bars()
    universe = _load_universe(td, cfg)
    imminent_only: list[str] = []
    for code in universe:
        bars = _load_bars_from_db(code, td, lookback)
        if bars is None or len(bars) < 70:
            continue
        mas = compute_mas(bars["close"].astype(float), cfg.compute_periods)
        if detect_ma5_ma10_cross(mas, cfg) != "imminent":
            continue
        cfg_old = cfg.model_copy(update={"require_ma5_ma10_cross": False})
        ok_old = (
            passes_ma_filter(mas, cfg_old)
            and passes_prior_surge_filter(bars, cfg, code)
            and passes_max_total_gain_filter(bars, cfg)
            and passes_volume_pullback_filter(bars, mas, cfg)
        )
        ok_new = (
            passes_ma_filter(mas, cfg)
            and passes_prior_surge_filter(bars, cfg, code)
            and passes_max_total_gain_filter(bars, cfg)
            and passes_volume_pullback_filter(bars, mas, cfg)
        )
        if ok_new and not ok_old:
            imminent_only.append(code)
    print(f"imminent-only new passes: {len(imminent_only)} {imminent_only[:15]}")

    td_hist = date(2026, 7, 2)
    _, hist_snaps = _screen(td_hist, True)
    rets = _forward_return(list(hist_snaps), td_hist, td)
    if rets:
        vals = list(rets.values())
        print(f"\n=== forward 5d return ({td_hist} -> {td}) ===")
        print(f"all n={len(vals)} mean={sum(vals)/len(vals):.2f}% median={sorted(vals)[len(vals)//2]:.2f}%")
        by_state: dict[str, list[float]] = {}
        for code, r in rets.items():
            st = hist_snaps[code].get("ma5_ma10_cross_state", "?")
            by_state.setdefault(st, []).append(r)
        for st, rs in sorted(by_state.items()):
            print(f"  {st}: n={len(rs)} mean={sum(rs)/len(rs):.2f}%")


if __name__ == "__main__":
    main()
