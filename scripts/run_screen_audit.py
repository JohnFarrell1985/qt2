"""MA 初筛执行与分阶段统计.

用法 (项目根目录):
  uv run python scripts/run_screen_audit.py
  uv run python scripts/run_screen_audit.py --date 2026-03-11
  uv run python scripts/run_screen_audit.py --audit
  uv run python scripts/run_screen_audit.py --scan 10

「日」均指交易日 (stock_daily K 线), 非自然日.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from src.common.config import apply_strategy, get_strategy_meta, list_strategies, settings
from src.common.db import get_engine
from src.selection.ma_screener import (
    compute_mas,
    passes_ma_filter,
    passes_max_total_gain_filter,
    passes_prior_surge_filter,
    passes_volume_pullback_filter,
    screen_universe,
    _load_bars_from_db,
    _load_universe,
)
from src.selection.workflow import save_report, output_path, candidates_filename, build_screen_report


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    return date.fromisoformat(s)


def db_status(min_codes: int = 5000) -> tuple[date | None, date | None, int]:
    """返回 (最新交易日, 最近全市场覆盖日, 该日股票数)."""
    with get_engine().connect() as conn:
        latest = conn.execute(text("SELECT MAX(trade_date) FROM stock_daily")).scalar()
        row = conn.execute(
            text("""
                SELECT trade_date, COUNT(DISTINCT code) AS n
                FROM stock_daily
                GROUP BY trade_date
                HAVING COUNT(DISTINCT code) > :min_codes
                ORDER BY trade_date DESC
                LIMIT 1
            """),
            {"min_codes": min_codes},
        ).fetchone()
    if row:
        return latest, row[0], int(row[1])
    return latest, None, 0


def print_db_status(min_codes: int = 5000) -> date | None:
    latest, full, n = db_status(min_codes)
    print("=== 数据库 K 线 ===")
    print(f"  最新交易日:     {latest}")
    print(f"  最近全市场覆盖: {full}  ({n} 只, >{min_codes})")
    return full


def _lookback_bars() -> int:
    cfg = settings.selection.ma_filter
    max_period = max(cfg.compute_periods)
    return max(
        max_period + cfg.prior_surge_lookback_days + 10,
        cfg.prior_surge_lookback_days + 5,
        cfg.max_gain_lookback_days + 5,
    )


def audit_one_day(trade_date: date) -> dict[str, int]:
    """单交易日: 各条件通过数及交集."""
    cfg = settings.selection.ma_filter
    max_period = max(cfg.compute_periods)
    lookback = _lookback_bars()
    universe = _load_universe(trade_date, cfg)

    counts = {
        "universe": len(universe),
        "ma_divergence": 0,
        "prior_surge": 0,
        "max_total_gain": 0,
        "volume_pullback": 0,
        "all_pass": 0,
    }
    for code in universe:
        bars = _load_bars_from_db(code, trade_date, lookback)
        if bars is None or len(bars) < max_period + 1:
            continue
        mas = compute_mas(bars["close"].astype(float), cfg.compute_periods)
        ok_ma = passes_ma_filter(mas, cfg)
        ok_surge = passes_prior_surge_filter(bars, cfg)
        ok_gain = passes_max_total_gain_filter(bars, cfg)
        ok_vol = passes_volume_pullback_filter(bars, mas, cfg)
        counts["ma_divergence"] += int(ok_ma)
        counts["prior_surge"] += int(ok_surge)
        counts["max_total_gain"] += int(ok_gain)
        counts["volume_pullback"] += int(ok_vol)
        ok_all = ok_ma and ok_surge and ok_gain
        if cfg.require_volume_pullback:
            ok_all = ok_all and ok_vol
        counts["all_pass"] += int(ok_all)
    return counts


def print_audit(trade_date: date) -> None:
    cfg = settings.selection.ma_filter
    print(f"\n=== 分阶段统计  {trade_date} (交易日) ===")
    prox = ""
    if cfg.require_volume_pullback and cfg.require_ma5_proximity:
        prox = f" | 收盘距MA{cfg.anchor_ma_period}<=±{cfg.ma5_proximity_pct}%"
        if cfg.require_low_above_ma5:
            prox += f"且低点不破MA{cfg.anchor_ma_period}"
    vol_rule = (
        f" | 相对上一交易日缩量(ratio<{cfg.volume_shrink_ratio}){prox}"
        if cfg.require_volume_pullback
        else " | [缩量 已关闭]"
    )
    print(
        f"  规则: 筛选日向上发散 | 前{cfg.prior_surge_lookback_days}个交易日有大涨"
        f"(>{cfg.prior_surge_min_pct}%) | 近{cfg.max_gain_lookback_days}日总涨幅"
        f"<={cfg.max_gain_total_pct}%"
        f"{vol_rule}"
    )
    c = audit_one_day(trade_date)
    print(f"  universe:          {c['universe']:>5}")
    print(f"  ① 当日向上发散:    {c['ma_divergence']:>5}")
    print(f"  ② 前N日有大涨:     {c['prior_surge']:>5}")
    print(f"  ③ 近N日涨幅<=上限: {c['max_total_gain']:>5}")
    if cfg.require_volume_pullback:
        print(f"  ④ 当日缩量:        {c['volume_pullback']:>5}" + ("" if cfg.require_ma5_proximity else "  (不含贴MA5)"))
        print(f"  全部满足:          {c['all_pass']:>5}")
    else:
        print(f"  ④ 当日缩量:        {c['volume_pullback']:>5}  (未启用)")
        print(f"  全部满足:          {c['all_pass']:>5}")


def scan_full_market_days(n_days: int, min_codes: int = 5000) -> None:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("""
                SELECT trade_date, COUNT(DISTINCT code) AS n
                FROM stock_daily
                GROUP BY trade_date
                HAVING COUNT(DISTINCT code) > :min_codes
                ORDER BY trade_date DESC
                LIMIT :limit
            """),
            {"min_codes": min_codes, "limit": n_days},
        ).fetchall()

    print(f"\n=== 最近 {n_days} 个全市场交易日扫描 (>{min_codes} 只) ===")
    print(f"{'日期':<12} {'MA':>6} {'大涨':>6} {'涨幅':>6} {'缩量':>6} {'全部':>6}")
    for td, _n in rows:
        c = audit_one_day(td)
        print(
            f"{td.isoformat():<12} "
            f"{c['ma_divergence']:>6} {c['prior_surge']:>6} "
            f"{c['max_total_gain']:>6} {c['volume_pullback']:>6} {c['all_pass']:>6}"
        )


def _print_rank_stats(trade_date: date, candidates: list[str], snapshots: dict[str, dict]) -> None:
    if not candidates:
        print("\n=== 排序分布 ===  无候选")
        return
    dists = [snapshots[c].get("ma5_dist_pct", 0) for c in candidates]
    tiers = {t: sum(1 for c in candidates if snapshots[c].get("tier") == t) for t in ("A", "B", "C")}
    print(f"\n=== 排序分布  {trade_date} ({len(candidates)} 只) ===")
    print(f"  tier A/B/C: {tiers.get('A', 0)} / {tiers.get('B', 0)} / {tiers.get('C', 0)}")
    print(f"  MA5距离<=1%: {sum(1 for d in dists if d <= 1.0)}")
    print(f"  MA5距离<=2%: {sum(1 for d in dists if d <= 2.0)}")
    print(f"  MA5距离<=3%: {sum(1 for d in dists if d <= 3.0)}")
    print("  Top5:")
    for code in candidates[:5]:
        s = snapshots[code]
        print(
            f"    {code}  score={s.get('composite_score')} tier={s.get('tier')}  "
            f"ma5_dist={s.get('ma5_dist_pct')}%  vol={s.get('vol_shrink_ratio')}"
        )


def print_rank_distribution(trade_date: date) -> None:
    """重跑初筛并打印排序分布 (--rank-dist --no-screen)."""
    candidates, snapshots = screen_universe(trade_date)
    _print_rank_stats(trade_date, candidates, snapshots)


def run_screen(trade_date: date, output: Path | None) -> tuple[list[str], dict]:
    candidates, snapshots = screen_universe(trade_date)
    report = build_screen_report(trade_date, candidates, snapshots)
    out = output or output_path(trade_date, candidates_filename(trade_date))
    save_report(report, out)
    print(f"\n=== 初筛结果 ===")
    print(f"  通过: {len(candidates)} 只")
    print(f"  输出: {out}")
    if candidates:
        for code in candidates[:20]:
            snap = snapshots.get(code, {})
            print(
                f"    {code}  score={snap.get('composite_score')} tier={snap.get('tier')}  "
                f"close={snap.get('close')}  ma5_dist={snap.get('ma5_dist_pct')}%  "
                f"vol_ratio={snap.get('vol_shrink_ratio')}  "
                f"max_surge={snap.get('max_prior_surge_pct')}%"
            )
        if len(candidates) > 20:
            print(f"    ... 共 {len(candidates)} 只, 详见 JSON")
    _print_rank_stats(trade_date, candidates, snapshots)
    return candidates, snapshots


def main() -> None:
    parser = argparse.ArgumentParser(description="MA 初筛 + 分阶段审计")
    parser.add_argument(
        "--date",
        help="筛选交易日 YYYY-MM-DD; 默认取最近全市场覆盖日",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="候选 JSON 输出路径",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="打印各条件通过数量 (可与 --screen 同用)",
    )
    parser.add_argument(
        "--scan",
        type=int,
        metavar="N",
        help="扫描最近 N 个全市场交易日并汇总",
    )
    parser.add_argument(
        "--no-screen",
        action="store_true",
        help="仅 status/audit/scan, 不执行初筛写文件",
    )
    parser.add_argument(
        "--rank-dist",
        action="store_true",
        help="打印候选 MA5 分档与 tier 分布 (会重跑初筛)",
    )
    parser.add_argument(
        "--strategy",
        choices=list_strategies(),
        help="选股策略 preset (默认 app.json / SELECTION_STRATEGY)",
    )
    parser.add_argument(
        "--min-codes",
        type=int,
        default=5000,
        help="全市场覆盖最少股票数 (默认 5000)",
    )
    args = parser.parse_args()

    if args.strategy:
        sid = apply_strategy(args.strategy)
        print(f"=== 策略: {get_strategy_meta().get('label', sid)} ({sid}) ===")
    else:
        meta = get_strategy_meta()
        print(f"=== 策略: {meta.get('label', settings.selection.active_strategy)} ({meta.get('id')}) ===")

    full_default = print_db_status(args.min_codes)

    if args.scan:
        scan_full_market_days(args.scan, args.min_codes)

    trade_date = _parse_date(args.date) or full_default
    if trade_date is None:
        print("错误: 无法确定筛选日期, 请用 --date 指定", file=sys.stderr)
        sys.exit(1)

    if args.audit or args.scan is None and not args.no_screen:
        print_audit(trade_date)

    if args.rank_dist and args.no_screen:
        print_rank_distribution(trade_date)

    if not args.no_screen:
        run_screen(trade_date, args.output)


if __name__ == "__main__":
    main()
