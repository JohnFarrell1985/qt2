"""检查 ``etf_info`` 与 ``etf_daily`` 覆盖: 对比每标有效地板与最早 K 线.

    uv run python -m src.data.etf_daily_audit --floor 20160101
    uv run python -m src.data.etf_daily_audit --floor 20160101 --all
    uv run python -m src.data.etf_daily_audit --floor 20160101 --csv gaps.csv
"""
from __future__ import annotations

import csv
from argparse import ArgumentParser
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text

from src.common.db import get_session
from src.data.akshare_financial_sync import AkshareFinancialSync
from src.data.models import ETFInfo


def _d(v: Any) -> date | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        s = str(v)[:10].replace("-", "")
        if len(s) >= 8:
            return datetime.strptime(s[:8], "%Y%m%d").date()
    except (TypeError, ValueError):
        pass
    return None


def run_audit(
    user_floor: str = "20160101",
    *,
    only_issues: bool = True,
    csv_path: str | None = None,
) -> int:
    sync = AkshareFinancialSync
    with get_session(readonly=True) as session:
        etf_rows = session.query(ETFInfo.code, ETFInfo.name, ETFInfo.establish_date).all()
        ag = session.execute(
            text(
                "SELECT code, MIN(trade_date), MAX(trade_date), COUNT(*)::bigint "
                "FROM etf_daily GROUP BY code",
            ),
        ).fetchall()
    agg: dict[str, tuple[Any, Any, int]] = {
        str(r[0]): (r[1], r[2], int(r[3] or 0)) for r in ag
    }

    today = date.today()
    out: list[dict[str, Any]] = []
    n_no = n_back = n_stale = n_ok = 0

    for code, name, est in etf_rows:
        t = agg.get(str(code))
        if t is None:
            min_t, max_t, cnt = None, None, 0
        else:
            min_t, max_t, cnt = t[0], t[1], t[2]
        min_s = str(min_t) if min_t else ""
        pcf = sync._per_code_floor(
            user_floor, est, min_s if len(min_s) >= 8 else None,
        )
        try:
            pcf_d = datetime.strptime(pcf, "%Y%m%d").date()
        except ValueError:
            pcf_d = None
        min_d, max_d = _d(min_t), _d(max_t)

        status, note = "ok", ""
        if min_d is None:
            status, note, n_no = "no_daily", "etf_daily 无行", n_no + 1
        elif pcf_d and min_d > pcf_d:
            status, note = "backfill", f"min {min_d} > 有效地板 {pcf_d}"
            n_back += 1
        elif max_d and (today - max_d) > timedelta(days=5):
            status, note, n_stale = "stale", f"max {max_d} 距今日>5天", n_stale + 1
        else:
            n_ok += 1

        row = {
            "code": code, "name": (name or "")[:80], "establish_date": str(est) if est else "",
            "effective_floor_ymd": pcf, "min_trade_date": str(min_t) if min_t else "",
            "max_trade_date": str(max_t) if max_t else "", "n_rows": cnt, "status": status,
            "note": note,
        }
        if not only_issues or status != "ok":
            out.append(row)

    issue_cnt = n_no + n_back + n_stale
    print("=== etf_info vs etf_daily 覆盖 (有效地板=max(用户地板,成立日)) ===", flush=True)  # noqa: T201
    print(  # noqa: T201
        f"user_floor={user_floor}  |  etf_info: {len(etf_rows)}  只有日线聚合: {len(agg)}  只",
        flush=True,
    )
    print(  # noqa: T201
        f"无日线: {n_no}  |  须向下补(最早>地板): {n_back}  |  "
        f"可能缺近端: {n_stale}  |  看起来正常: {n_ok}",
        flush=True,
    )
    for r in out[:100]:
        print(  # noqa: T201
            f"  {r['status']!s:10}  {r['code']!s:14}  min={r['min_trade_date']!s:12}  "
            f"floor={r['effective_floor_ymd']!s:8}  n={r['n_rows']!s:8}  {r['note']}",
            flush=True,
        )
    if len(out) > 100:
        print(f"  … 其余 {len(out) - 100} 行省略", flush=True)  # noqa: T201

    if csv_path and out:
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(out[0].keys()))
            w.writeheader()
            w.writerows(out)
        print("已写 CSV:", csv_path, flush=True)  # noqa: T201
    return issue_cnt


if __name__ == "__main__":
    ap = ArgumentParser()
    ap.add_argument("--floor", default="20160101", help="与 sync_etf_daily --start-date 一致")
    ap.add_argument("--all", action="store_true", help="打印含 status=ok 的全集")
    ap.add_argument("--csv", default="", help="有问题行的 CSV 路径")
    a = ap.parse_args()
    n = run_audit(a.floor, only_issues=not a.all, csv_path=a.csv or None)
    raise SystemExit(1 if n else 0)
