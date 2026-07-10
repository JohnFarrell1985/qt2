"""审查近一年 ETF 日K 完整性并输出报告."""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text

from src.common.config import PROJECT_ROOT
from src.common.db import get_session


def audit(year_days: int = 365) -> dict:
    end = date.today()
    start = end - timedelta(days=year_days)
    with get_session() as s:
        n_days = s.execute(
            text(
                "SELECT COUNT(DISTINCT trade_date) FROM stock_daily "
                "WHERE trade_date BETWEEN :s AND :e"
            ),
            {"s": start, "e": end},
        ).scalar()
        etf_total = s.execute(text("SELECT COUNT(*) FROM etf_info")).scalar()
        rows = s.execute(
            text(
                """
                SELECT e.code, e.name, e.establish_date,
                       COUNT(sd.trade_date) AS cnt,
                       MIN(sd.trade_date) AS min_d,
                       MAX(sd.trade_date) AS max_d
                FROM etf_info e
                LEFT JOIN etf_daily sd
                  ON e.code = sd.code AND sd.trade_date BETWEEN :s AND :e
                GROUP BY e.code, e.name, e.establish_date
                ORDER BY cnt ASC, e.code
                """
            ),
            {"s": start, "e": end},
        ).fetchall()

    full = [r for r in rows if r[3] == n_days]
    partial = [r for r in rows if 0 < r[3] < n_days]
    empty = [r for r in rows if r[3] == 0]

    # 按上市日口径: 每只 ETF 在 [max(establish, window_start), end] 内应有的交易日数
    with get_session() as s:
        tdays = sorted(
            r[0]
            for r in s.execute(
                text(
                    "SELECT DISTINCT trade_date FROM stock_daily "
                    "WHERE trade_date BETWEEN :s AND :e ORDER BY 1"
                ),
                {"s": start, "e": end},
            ).fetchall()
        )
    listing_aware_incomplete = []
    listing_aware_complete = 0
    for r in rows:
        floor = max(r[2] or start, start)
        expected = sum(1 for d in tdays if d >= floor)
        if r[3] >= expected:
            listing_aware_complete += 1
        elif expected > 0:
            listing_aware_incomplete.append({
                "code": r[0],
                "name": r[1],
                "rows": r[3],
                "expected_in_window": expected,
                "floor": floor.isoformat(),
                "min_d": r[4].isoformat() if r[4] else None,
                "max_d": r[5].isoformat() if r[5] else None,
                "missing": expected - r[3],
            })

    true_gap = []
    new_listing = []
    for r in partial:
        est = r[2]
        min_d = r[4]
        if (est and est > start) or (min_d and min_d > start + timedelta(days=30)):
            new_listing.append(r)
        else:
            true_gap.append(r)

    actual_rows = sum(r[3] for r in rows)
    expected = etf_total * n_days
    listing_expected_rows = sum(
        sum(1 for d in tdays if d >= max(r[2] or start, start)) for r in rows
    )
    return {
        "audit_date": end.isoformat(),
        "window_start": start.isoformat(),
        "window_end": end.isoformat(),
        "trading_days": n_days,
        "etf_total": etf_total,
        "etfs_full_year": len(full),
        "etfs_partial": len(partial),
        "etfs_empty": len(empty),
        "listing_aware_complete": listing_aware_complete,
        "listing_aware_incomplete": len(listing_aware_incomplete),
        "listing_aware_coverage_pct": round(
            100 * listing_aware_complete / etf_total, 2
        ) if etf_total else 0,
        "likely_new_listing": len(new_listing),
        "likely_true_gap": len(true_gap),
        "actual_rows": actual_rows,
        "expected_rows_if_full_grid": expected,
        "expected_rows_listing_aware": listing_expected_rows,
        "coverage_pct": round(100 * actual_rows / expected, 2) if expected else 0,
        "listing_aware_rows_coverage_pct": round(
            100 * actual_rows / listing_expected_rows, 2
        ) if listing_expected_rows else 0,
        "missing_rows": expected - actual_rows,
        "listing_aware_incomplete_list": listing_aware_incomplete,
        "true_gap_samples": [
            {
                "code": r[0],
                "name": r[1],
                "rows": r[3],
                "min_d": r[4].isoformat() if r[4] else None,
                "max_d": r[5].isoformat() if r[5] else None,
            }
            for r in true_gap[:30]
        ],
        "worst_partial": [
            {
                "code": r[0],
                "name": r[1],
                "rows": r[3],
                "min_d": r[4].isoformat() if r[4] else None,
                "max_d": r[5].isoformat() if r[5] else None,
            }
            for r in partial[:20]
        ],
    }


def main() -> int:
    report = audit()
    out = PROJECT_ROOT / "reports" / f"etf_yearly_audit_{report['audit_date'].replace('-', '')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\n报告已保存: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
