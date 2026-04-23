"""统计各 ETF 在统计窗口内是否已尽量拉全, 并对齐 ``etf_download_progress``.

说明 (与「约 10 年 / 约 2016 年起」的口头目标一致, 不苛求每只都从同一天上市):
- 窗口下沿 ``window_start``: 默认可用 ``--as-of`` 与 ``--years`` 推出来; 或显式 ``--window-start 2016-01-01``
  表示「最早关心从哪一天起的缺口」(口头上 2016-01-01 亦可).
- 单日标的**有效起算日** ``t0 = max(window_start, 成立日, 该标的首根 K 的日期)`` —— **晚于窗口的新基金**
  只按**上市/有 K 之后**的交易日数记预期, 不会按满 10 年去算「缺了几千根」.
- **预期条数** ``expected``: 在 [t0, as_of] 内、且落在全库在 [window_start, as_of] 出现过的**交易日集合**中的天数
  (用库内已有任意 ETF 的日频并集近似沪深交易日).
- **实际条数** ``actual``: 仅统计 ``etf_daily`` 中该标的、且 ``trade_date`` 落在 **[t0, as_of]** 上的行数
  (与 expected 同口径, 避免把 2016 年以前的存量 K 算进分母/分子错位).

  uv run python scripts/etf_daily_coverage_and_align.py
  uv run python scripts/etf_daily_coverage_and_align.py --window-start 2016-01-01 --as-of 2026-04-22
"""
from __future__ import annotations

import argparse
import bisect
import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from dateutil.relativedelta import relativedelta
from sqlalchemy import func, text

from src.common.config import settings
from src.common.db import get_session
from src.common.logger import get_logger
from src.data.etf_download_progress import (
    ETF_SYNC_TYPE_DAILY,
    EtfDownloadProgressDAO,
)
from src.data.models import ETFDaily, ETFInfo, EtfDownloadProgress

logger = get_logger(__name__)


@dataclass
class RowStat:
    code: str
    t0: date
    expected: int
    actual: int  # 仅 [t0, as_of] 内行数, 与 expected 同口径
    min_d_all: date | None  # 库内该标的全历史最早日 (供参考, 不直接参与与 expected 比)
    max_d: date | None  # 库内 [t0,as_of] 上最后一根, 用于新鲜度
    ratio: float
    complete: bool


def _parse_date(s: str) -> date:
    return datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", default="2026-04-22", help="统计截止日 YYYY-MM-DD")
    ap.add_argument(
        "--window-start",
        default=None,
        help="窗口下沿 YYYY-MM-DD; 不设则 win_start = as_of 减 --years 年 (口头上「约 2016-01-01」可设本项)",
    )
    ap.add_argument(
        "--years",
        type=int,
        default=10,
        help="未指定 --window-start 时, win_start = as_of 往前推 N 个整年",
    )
    ap.add_argument(
        "--min-pct",
        type=float,
        default=0.98,
        help="实际/预期 >= 该比例且最新日足够新则判为已拉满",
    )
    ap.add_argument(
        "--max-lag-days",
        type=int,
        default=7,
        help="max(trade_date) 允许落后 as-of 的自然日(非交易日)",
    )
    ap.add_argument("--dry-run", action="store_true", help="只统计/打印, 不写库")
    ap.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="可选: 导出明细 CSV 路径",
    )
    args = ap.parse_args()

    as_of = _parse_date(args.as_of)
    if args.window_start:
        win_start = _parse_date(args.window_start)
    else:
        win_start = as_of - relativedelta(years=args.years)
    if win_start > as_of:
        logger.error("window_start %s 晚于 as_of %s", win_start, as_of)
        return 1
    mr = int(settings.datacollect.etf_download_max_retries)

    with get_session(readonly=True) as session:
        mkt_q = (
            session.query(ETFDaily.trade_date)
            .filter(
                ETFDaily.trade_date >= win_start,
                ETFDaily.trade_date <= as_of,
            )
            .distinct()
        )
        mkt_days: list[date] = sorted({r[0] for r in mkt_q if r[0] is not None})

    if not mkt_days:
        logger.error("在 [%s, %s] 内 etf_daily 无任意交易日样例, 无法构造交易日历", win_start, as_of)
        return 1

    with get_session(readonly=True) as session:
        irows = session.query(ETFInfo.code, ETFInfo.establish_date).all()
    # 每标的: 全表最早日 (定 t0 用); 与 expected 对比的条数、窗口内 max 日 在下列循环内按 t0 现算
    minmax: dict[str, tuple[date | None, date | None]] = {}
    with get_session(readonly=True) as session:
        q = (
            session.query(
                ETFDaily.code,
                func.min(ETFDaily.trade_date),
                func.max(ETFDaily.trade_date),
            ).group_by(ETFDaily.code)
        )
        for code, mi, ma in q:
            minmax[code] = (mi, ma)

    stats: list[RowStat] = []
    with get_session(readonly=True) as session:
        for code, est in irows:
            min_d_all, _max_all = minmax.get(code, (None, None))
            if est is None:
                est_d = None
            elif isinstance(est, datetime):
                est_d = est.date()
            else:
                est_d = est
            # 晚于窗口上市的标的: 起算日不早于成立/首 K, 也不早于全窗口下沿
            t_candidates = [win_start, est_d, min_d_all]
            t0 = max(d for d in t_candidates if d is not None)
            if t0 > as_of:
                exp = 0
                actual = 0
                max_d = None
                r = 1.0 if (min_d_all is None) else 0.0
            else:
                i0 = bisect.bisect_left(mkt_days, t0)
                i1 = bisect.bisect_right(mkt_days, as_of)
                exp = i1 - i0
                qwin = session.query(
                    func.count(ETFDaily.id),
                    func.max(ETFDaily.trade_date),
                ).filter(
                    ETFDaily.code == code,
                    ETFDaily.trade_date >= t0,
                    ETFDaily.trade_date <= as_of,
                )
                _cnt, _mx = qwin.one()
                actual = int(_cnt or 0)
                max_d = _mx
                r = (float(actual) / exp) if exp > 0 else (1.0 if actual == 0 else 0.0)
            fresh = (
                max_d is not None
                and (as_of - max_d) <= timedelta(days=int(args.max_lag_days))
            )
            complete = bool(
                exp > 0
                and actual >= int(exp * float(args.min_pct))
                and fresh
            )
            if exp == 0 and min_d_all is None and actual == 0:
                complete = False
            stats.append(
                RowStat(
                    code=code,
                    t0=t0,
                    expected=exp,
                    actual=actual,
                    min_d_all=min_d_all,
                    max_d=max_d,
                    ratio=r,
                    complete=complete,
                ),
            )

    n_ok = sum(1 for s in stats if s.complete)
    n_incomplete = len(stats) - n_ok
    print(
        f"窗口下沿 {win_start} 截止 {as_of} 内(任意标的拼出的)交易日 {len(mkt_days)} 天; "
        f"单标预期从 t0=max(下沿,成立,首K) 起算; 标的数 {len(stats)}; "
        f"判满(>={int(100 * float(args.min_pct))}% 且 max 距 as-of ≤{args.max_lag_days}d): {n_ok}; 未满: {n_incomplete}",
    )
    if n_incomplete and n_incomplete <= 40:
        for s in stats:
            if not s.complete:
                print(
                    f"  未满 {s.code} 预期={s.expected} 实际(窗内)={s.actual} 比={s.ratio:.3f} "
                    f"min(全)={s.min_d_all} max(窗)={s.max_d} t0={s.t0}",
                )
    elif n_incomplete:
        for s in sorted(
            (x for x in stats if not x.complete),
            key=lambda x: (x.ratio if x.expected else 0, -x.actual),
        )[:25]:
            print(
                f"  样本未满 {s.code} 预={s.expected} 实(窗)={s.actual} 比={s.ratio:.3f} max(窗)={s.max_d}",
            )

    if args.csv:
        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with args.csv.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(
                "code t0 expected actual_in_window min_d_all max_d_in_window ratio complete".split(),
            )
            for s in stats:
                w.writerow(
                    [
                        s.code,
                        s.t0.isoformat(),
                        s.expected,
                        s.actual,
                        s.min_d_all.isoformat() if s.min_d_all else "",
                        s.max_d.isoformat() if s.max_d else "",
                        f"{s.ratio:.6f}",
                        s.complete,
                    ],
                )
        print("已写 CSV:", args.csv.resolve())

    if args.dry_run:
        print("[dry-run] 跳过 etf_download_progress 对齐与 max_retries 更新", flush=True)
        return 0

    with get_session() as session:
        session.execute(
            text(
                """
                UPDATE etf_download_progress
                SET max_retries = :mr, updated_at = NOW()
                WHERE sync_type = :st
                """,
            ),
            {"mr": mr, "st": ETF_SYNC_TYPE_DAILY},
        )
    n_up = 0
    with get_session() as session:
        by_code = {s.code: s for s in stats}
        rows = (
            session.query(EtfDownloadProgress)
            .filter(EtfDownloadProgress.sync_type == ETF_SYNC_TYPE_DAILY)
            .all()
        )
        for row in rows:
            st = by_code.get(row.code)
            if st is None:
                continue
            row.max_retries = mr
            row.start_date = win_start
            row.end_date = as_of
            row.expected_count = st.expected
            row.records_count = st.actual
            # 与「本窗口内有效根」对齐: 起点用有效 t0(计划覆盖下沿), 有数据时用窗内最早日更直观可再手查 min_d_all
            row.actual_start_date = st.t0
            row.actual_end_date = st.max_d
            if st.complete:
                row.status = "success"
                row.error_message = None
                row.completed_at = datetime.now()
            else:
                if row.status == "success" and not st.complete:
                    row.status = "pending"
                row.completed_at = None
        n_up = len(rows)

    all_codes = [c for c, _ in irows]
    with get_session(readonly=True) as session:
        have = {
            r[0]
            for r in session.query(EtfDownloadProgress.code)
            .filter(EtfDownloadProgress.sync_type == ETF_SYNC_TYPE_DAILY)
            .all()
        }
    need = [c for c in all_codes if c not in have]
    if need:
        EtfDownloadProgressDAO.init_progress(
            need,
            ETF_SYNC_TYPE_DAILY,
            win_start,
            as_of,
            max_retries=mr,
        )
        n_up += len(need)

    with get_session() as session:
        for code in need:
            st = by_code[code]
            r = (
                session.query(EtfDownloadProgress)
                .filter(
                    EtfDownloadProgress.code == code,
                    EtfDownloadProgress.sync_type == ETF_SYNC_TYPE_DAILY,
                )
                .first()
            )
            if r:
                r.expected_count = st.expected
                r.records_count = st.actual
                r.actual_start_date = st.t0
                r.actual_end_date = st.max_d
                r.max_retries = mr
                if st.complete:
                    r.status = "success"
                    r.completed_at = datetime.now()
                else:
                    r.status = "pending"

    print(
        f"已更新 etf_download_progress: 全表 max_retries={mr}, 对齐了 {n_up} 行(含补充缺失标的 {len(need)});"
        f" 判满 {n_ok} / {len(stats)}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
