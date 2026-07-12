"""机构持有家数同步 — 按报告期批量落库 (类似另类日频)

用法:
  uv run python -m src.data.inst_holder_sync --year 2026
  uv run python -m src.data.inst_holder_sync --report-date 2026-03-31
  uv run python -m src.data.inst_holder_sync --years 2024-2026
"""
from __future__ import annotations

import argparse
from datetime import date, datetime

from src.common.db_batch import log_upsert_commit
from src.common.logger import get_logger
from src.data.alt_datacollect_progress import AltDatacollectProgressDAO, CAT_INST_HOLDER
from src.data.inst_holder_em import (
    current_year_report_dates,
    em_total_for_date,
    fetch_all_for_report_date,
    standard_report_dates,
)
from src.data.inst_holder_store import count_for_report_date, upsert_rows

logger = get_logger(__name__)

_MIN_BULK_ROWS = 500


def _scope_key(report_date: date) -> str:
    return report_date.strftime("%Y%m%d")


def sync_report_date(report_date: date, *, force: bool = False) -> int:
    """同步单个报告期的全市场机构家数。返回写入行数。"""
    rd_str = report_date.isoformat()
    sk = _scope_key(report_date)
    src_id = "eastmoney"

    if not force and AltDatacollectProgressDAO.is_ok(CAT_INST_HOLDER, sk, src_id):
        n = count_for_report_date(report_date)
        logger.info("机构家数 %s 已同步 (跳过), DB %d 行", rd_str, n)
        return n

    try:
        api_total = em_total_for_date(rd_str)
    except Exception as e:  # noqa: BLE001
        logger.error("机构家数 %s 东财统计失败: %s", rd_str, e)
        AltDatacollectProgressDAO.mark_ok(CAT_INST_HOLDER, sk, src_id, 0, status="error")
        return 0

    if api_total == 0:
        logger.warning("机构家数 %s 东财无数据", rd_str)
        AltDatacollectProgressDAO.mark_ok(CAT_INST_HOLDER, sk, src_id, 0, status="empty")
        return 0

    logger.info("机构家数 %s 东财共 %d 条, 开始拉取…", rd_str, api_total)
    try:
        rows = fetch_all_for_report_date(rd_str)
    except Exception as e:  # noqa: BLE001
        logger.error("机构家数 %s 拉取失败: %s", rd_str, e)
        AltDatacollectProgressDAO.mark_ok(CAT_INST_HOLDER, sk, src_id, 0, status="error")
        return 0

    if not rows:
        AltDatacollectProgressDAO.mark_ok(CAT_INST_HOLDER, sk, src_id, 0, status="empty")
        return 0

    now = datetime.now()
    for r in rows:
        r["created_at"] = now
        r["updated_at"] = now

    n = upsert_rows(rows)
    log_upsert_commit("inst_holder.stock_inst_holder", n)
    complete_n = sum(1 for r in rows if r.get("is_complete"))
    AltDatacollectProgressDAO.mark_ok(CAT_INST_HOLDER, sk, src_id, n, status="ok")
    logger.info("机构家数 %s 落库 %d 行 (完整 %d)", rd_str, n, complete_n)
    return n


def sync_years(start_year: int, end_year: int, *, force: bool = False) -> int:
    """同步区间内全部标准报告日 (仅同步已到达的日期)。"""
    today = date.today()
    dates = [d for d in standard_report_dates(start_year, end_year) if d <= today]
    total = 0
    for rd in dates:
        total += sync_report_date(rd, force=force)
    return total


def sync_current_year(*, force: bool = False) -> int:
    """同步当年已到达的标准报告日。"""
    today = date.today()
    dates = [date.fromisoformat(d) for d in current_year_report_dates(today)]
    total = 0
    for rd in dates:
        try:
            api_n = em_total_for_date(rd.isoformat())
        except Exception:  # noqa: BLE001
            api_n = 0
        if api_n < _MIN_BULK_ROWS and not force:
            logger.info("机构家数 %s 东财仅 %d 条, 跳过 (不完整批次)", rd, api_n)
            continue
        total += sync_report_date(rd, force=force)
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description="同步机构持有家数到 stock_inst_holder")
    parser.add_argument("--year", type=int, help="同步指定年份")
    parser.add_argument("--years", type=str, help="年份区间 如 2024-2026")
    parser.add_argument("--report-date", type=str, help="单个报告日 YYYY-MM-DD")
    parser.add_argument("--current-year", action="store_true", help="同步当年完整批次 (默认行为)")
    parser.add_argument("--force", action="store_true", help="忽略进度表强制重拉")
    args = parser.parse_args()

    if args.report_date:
        n = sync_report_date(date.fromisoformat(args.report_date), force=args.force)
    elif args.year:
        n = sync_years(args.year, args.year, force=args.force)
    elif args.years:
        a, b = args.years.split("-", 1)
        n = sync_years(int(a), int(b), force=args.force)
    else:
        n = sync_current_year(force=args.force)

    logger.info("机构家数同步完成, 共写入/确认 %d 行", n)


if __name__ == "__main__":
    main()
