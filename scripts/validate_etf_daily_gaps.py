"""校验 etf_daily 在各自有数据的时间窗内, 相对 XSHG 是否「交易日无缺口」.

定义: 对每只 ETF, 设窗为 [该 code 在表内 MIN(trade_date), MAX(trade_date)]; 任一时间若属于
exchange_calendars 的 XSHG 交易会话, 则必须在 etf_daily 中存在 (code, trade_date) 行.

    uv run python scripts/validate_etf_daily_gaps.py
    uv run python scripts/validate_etf_daily_gaps.py --max-codes 50   # 调试用
    uv run python scripts/validate_etf_daily_gaps.py --export gaps.csv
"""
from __future__ import annotations

import argparse
import csv
from bisect import bisect_left, bisect_right
from collections import defaultdict
from collections.abc import Iterator
from datetime import date, datetime

import pandas as pd
from sqlalchemy import text

from src.common.db import get_session


def _load_xshg_sessions(overall_start: date, overall_end: date) -> list[date]:
    import exchange_calendars as ec

    cal = ec.get_calendar("XSHG")
    sess = cal.sessions_in_range(
        pd.Timestamp(overall_start),
        pd.Timestamp(overall_end),
    )
    return [ts.date() for ts in sess]


def _iter_etf_bounds() -> Iterator[tuple[str, date, date, int]]:
    with get_session(readonly=True) as session:
        rows = session.execute(
            text("""
                SELECT code,
                       MIN(trade_date) AS dmin,
                       MAX(trade_date) AS dmax,
                       COUNT(*)::bigint AS n
                FROM etf_daily
                GROUP BY code
                ORDER BY code
            """),
        )
        for r in rows:
            yield (str(r[0]), r[1], r[2], int(r[3]))


def _load_dates_by_code() -> dict[str, set[date]]:
    by_code: dict[str, set[date]] = defaultdict(set)
    with get_session(readonly=True) as session:
        rows = session.execute(
            text("SELECT code, trade_date FROM etf_daily"),
        )
        for code, td in rows:
            if isinstance(td, datetime):
                td = td.date()
            by_code[str(code)].add(td)
    return by_code


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--max-codes",
        type=int,
        default=0,
        help="仅检查前 N 个 code(按字母序), 0=全部",
    )
    ap.add_argument(
        "--export",
        type=str,
        default="",
        help="将缺口逐行写出 CSV: code,trade_date",
    )
    ap.add_argument(
        "--summary-only",
        action="store_true",
        help="不逐条打印, 只输出汇总与缺口最多的标的",
    )
    ap.add_argument(
        "--top",
        type=int,
        default=20,
        help="summary-only 时列出缺口行数最多的前 N 个 code (默认 20)",
    )
    args = ap.parse_args()

    bounds: list[tuple[str, date, date, int]] = list(_iter_etf_bounds())
    if not bounds:
        print("etf_daily 无数据, 结束")
        return 1

    if args.max_codes > 0:
        bounds = bounds[: args.max_codes]

    g_min = min(b[1] for b in bounds)
    g_max = max(b[2] for b in bounds)
    all_sessions = _load_xshg_sessions(g_min, g_max)
    if not all_sessions:
        print("XSHG 在区间内无交易日, 请检查 exchange_calendars")
        return 1

    by_code = _load_dates_by_code()

    total_gaps = 0
    codes_with_gaps = 0
    rows_for_csv: list[tuple[str, str]] = [("code", "trade_date")]
    by_gap_desc: list[tuple[int, str, date, date, int, list[date]]] = []

    for code, dmin, dmax, n in bounds:
        actual = by_code.get(code, set())
        if len(actual) != n:
            # 理论不应出现
            print("warn: 计数与集合不一致", code, n, len(actual))

        lo = bisect_left(all_sessions, dmin)
        hi = bisect_right(all_sessions, dmax)
        expected = all_sessions[lo:hi]
        missing = [d for d in expected if d not in actual]
        if missing:
            codes_with_gaps += 1
            ng = len(missing)
            total_gaps += ng
            for d in missing:
                rows_for_csv.append((code, d.isoformat()))
            by_gap_desc.append((ng, code, dmin, dmax, n, missing))
            if not args.summary_only:
                print(
                    f"  {code} 缺口 {ng} 个, 窗 {dmin}~{dmax}, 行数 {n}, "
                    f"示例: {','.join(x.isoformat() for x in missing[:5])}"
                    f"{'…' if len(missing) > 5 else ''}",
                )

    print()
    print(f"XSHG 全历区间(合并窗): {g_min} ~ {g_max} , 共 {len(all_sessions)} 个会话(全局切片用)")
    print(f"已检查 code 数: {len(bounds)}")
    print(f"存在缺口的 code 数: {codes_with_gaps}")
    print(f"缺口交易日行总数(可重复 code): {total_gaps}")
    if by_gap_desc and args.summary_only:
        by_gap_desc.sort(key=lambda x: -x[0])
        ntop = max(0, int(args.top))
        print()
        print(f"缺口行数最多的前 {ntop} 个标的:")
        for ng, code, dmin, dmax, nrow, miss in by_gap_desc[:ntop]:
            ex = ",".join(x.isoformat() for x in miss[:3])
            more = "…" if len(miss) > 3 else ""
            print(f"  {code} 缺 {ng} 天, 表内行 {nrow}, 窗 {dmin}~{dmax}, 示例: {ex}{more}")

    if args.export and rows_for_csv[1:]:
        out_path = args.export
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(rows_for_csv)
        print(f"已写出: {out_path} ({len(rows_for_csv) - 1} 行)")

    if total_gaps == 0:
        print("结果: 在 [MIN, MAX] 窗内与 XSHG 交易日对齐, 未发现缺口。")
        return 0
    print("结果: 发现缺口(中间停牌/退市/源站漏抓等均可能, 需人工看标的)。")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
