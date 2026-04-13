"""数据完整性检查与自动补完调度器

功能:
1. 检查各数据表的完整性 (空表、缺口、覆盖率)
2. 按优先级自动补完: 交易日历 > 板块数据 > 可转债 > 财报
3. CLI: python -m src.data.data_completeness [check|backfill|all]
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import text

from src.common.db import get_engine, get_session
from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TableStatus:
    name: str
    row_count: int = 0
    date_range: str = ""
    issue: str = ""
    priority: int = 99  # lower = higher priority


@dataclass
class CompletenessReport:
    checked_at: datetime = field(default_factory=datetime.now)
    statuses: list[TableStatus] = field(default_factory=list)
    issues: list[TableStatus] = field(default_factory=list)


# ====================================================================
# 检查
# ====================================================================

def check_completeness() -> CompletenessReport:
    """全面检查数据库各表的完整性, 返回报告。"""
    engine = get_engine()
    report = CompletenessReport()

    with engine.connect() as conn:
        _check_trading_date(conn, report)
        _check_sector_data(conn, report)
        _check_convertible_bond(conn, report)
        _check_financial_reports(conn, report)
        _check_kline_gaps(conn, report)
        _check_empty_tables(conn, report)

    report.issues = [s for s in report.statuses if s.issue]
    report.issues.sort(key=lambda s: s.priority)
    return report


def _check_trading_date(conn, report: CompletenessReport):
    row = conn.execute(text("SELECT COUNT(*) FROM trading_date")).scalar()
    s = TableStatus("trading_date", row)
    if row == 0:
        s.issue = "交易日历表为空, 策略回测和因子计算依赖此表"
        s.priority = 1
    report.statuses.append(s)


def _check_sector_data(conn, report: CompletenessReport):
    r = conn.execute(text("""
        SELECT COUNT(*) as rows, COUNT(DISTINCT trade_date) as days,
               MIN(trade_date)::text, MAX(trade_date)::text
        FROM sector_data
    """)).fetchone()
    s = TableStatus("sector_data", r[0], f"{r[2]} ~ {r[3]}")
    if r[1] <= 5:
        s.issue = f"板块数据仅 {r[1]} 个交易日, 需补历史数据"
        s.priority = 2
    report.statuses.append(s)


def _check_convertible_bond(conn, report: CompletenessReport):
    cb = conn.execute(text("SELECT COUNT(*) FROM convertible_bond")).scalar()
    cbd = conn.execute(text("SELECT COUNT(*) FROM cb_daily")).scalar()
    s = TableStatus("convertible_bond", cb)
    if cb < 100:
        s.issue = f"可转债仅 {cb} 只 (市场约 500+), 需更新列表"
        s.priority = 3
    report.statuses.append(s)

    s2 = TableStatus("cb_daily", cbd)
    if cbd == 0 and cb > 0:
        s2.issue = "可转债日线为空, 需同步行情数据"
        s2.priority = 3
    report.statuses.append(s2)


def _check_financial_reports(conn, report: CompletenessReport):
    r = conn.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM stocks) as total_stocks,
            (SELECT COUNT(DISTINCT code) FROM stock_financial_report
             WHERE report_date >= CURRENT_DATE - INTERVAL '365 days') as fr_codes
    """)).fetchone()
    total, covered = r[0], r[1]
    gap = total - covered
    s = TableStatus("stock_financial_report", covered)
    if gap > 100:
        s.issue = f"{gap} 只股票缺失近一年财报数据"
        s.priority = 4
    report.statuses.append(s)


def _check_kline_gaps(conn, report: CompletenessReport):
    r = conn.execute(text("""
        SELECT COUNT(*) FROM stocks s
        WHERE NOT EXISTS (
            SELECT 1 FROM stock_daily sd
            WHERE sd.code = s.code
            AND sd.trade_date >= CURRENT_DATE - INTERVAL '365 days'
        )
    """)).scalar()
    s = TableStatus("stock_daily_gap", r)
    if r > 50:
        s.issue = f"{r} 只股票缺失日K (多为退市/停牌股, 可忽略)"
        s.priority = 8
    report.statuses.append(s)


def _check_empty_tables(conn, report: CompletenessReport):
    from sqlalchemy import inspect as sa_inspect
    insp = sa_inspect(get_engine())
    for tname in sorted(insp.get_table_names()):
        existing = [s.name for s in report.statuses]
        if tname in existing:
            continue
        cnt = conn.execute(text(f'SELECT COUNT(*) FROM "{tname}"')).scalar()
        s = TableStatus(tname, cnt)
        if cnt == 0 and tname not in (
            "ml_model_log", "ml_prediction", "trade_order",
            "trade_position", "trade_daily_report", "strategy",
            "strategy_allocation", "instrument_pool", "macro_state_log",
            "stock_minute", "stock_realtime", "watchlist_stock",
            "watchlist_intel", "sentiment_daily", "sentiment_ingest_log",
            "collect_log", "collect_dead_letter",
        ):
            s.issue = f"表 {tname} 为空"
            s.priority = 9
        report.statuses.append(s)


# ====================================================================
# 补完
# ====================================================================

def backfill_trading_date() -> int:
    """从 akshare 获取交易日历并写入 trading_date 表。"""
    import akshare as ak
    from sqlalchemy.dialects.postgresql import insert
    from src.data.models import TradingDate
    from src.datacollect.rate_limiter import TokenBucketLimiter
    from src.common.config import settings

    limiter = TokenBucketLimiter.for_domain(
        "akshare", rate=settings.datacollect.akshare_rate,
        burst=settings.datacollect.akshare_burst,
    )

    total = 0
    for market in ("SSE", "SZSE"):
        db_market = "SH" if market == "SSE" else "SZ"
        try:
            limiter.acquire()
            df = ak.tool_trade_date_hist_sina()
        except Exception as e:
            logger.error("获取交易日历失败 (%s): %s", market, e)
            continue

        if df is None or df.empty:
            continue

        col = "trade_date" if "trade_date" in df.columns else df.columns[0]
        rows = []
        for _, row in df.iterrows():
            try:
                td = row[col]
                if hasattr(td, "date"):
                    td = td.date()
                elif isinstance(td, str):
                    td = datetime.strptime(td[:10], "%Y-%m-%d").date()
                rows.append({
                    "market": db_market,
                    "trade_date": td,
                    "is_holiday": False,
                })
            except Exception:
                continue

        if rows:
            with get_session() as session:
                for i in range(0, len(rows), 1000):
                    batch = rows[i:i + 1000]
                    stmt = insert(TradingDate).values(batch)
                    stmt = stmt.on_conflict_do_nothing(
                        constraint="uq_trading_date",
                    )
                    session.execute(stmt)
            total += len(rows)
            logger.info("交易日历 %s: %d 条", db_market, len(rows))
        break  # Sina 返回的是通用日历, 不区分交易所

    logger.info("交易日历补完完成: %d 条", total)
    return total


def backfill_sector_data(start_date: str = "20250101") -> int:
    """补完板块行情历史数据。"""
    from src.data.sector_market_data import SectorMarketSync

    logger.info("开始补完板块数据 (%s ~ 今天)...", start_date)
    sync = SectorMarketSync()
    return sync.sync_sector_data(start_date=start_date)


def backfill_convertible_bond() -> int:
    """补完可转债列表 + 日线。"""
    from src.data.cb_sync import CBDataSync

    logger.info("开始补完可转债数据...")
    sync = CBDataSync()
    n1 = sync.sync_cb_list()
    logger.info("可转债列表: %d 只", n1)
    n2 = sync.sync_cb_daily(start_date="20250101")
    logger.info("可转债日线: %d 条", n2)
    return n1 + n2


def backfill_financial(mode: str = "batch") -> int:
    """补完财报数据。mode='batch' 用批量接口, 'single' 逐股。"""
    from src.data.akshare_financial_sync import AkshareFinancialSync

    logger.info("开始补完财报数据 (mode=%s)...", mode)
    sync = AkshareFinancialSync()
    total = 0
    if mode == "batch":
        total += sync.sync_financial_report_batch()
        total += sync.sync_financial_indicator_batch()
    else:
        total += sync.sync_financial_report()
        total += sync.sync_financial_indicator()
    return total


def run_backfill(skip_financial: bool = False):
    """按优先级执行所有补完任务。"""
    report = check_completeness()

    for item in report.issues:
        logger.info("[P%d] %s: %s", item.priority, item.name, item.issue)

    if not report.issues:
        logger.info("所有数据表完整, 无需补完")
        return

    for item in report.issues:
        try:
            if item.name == "trading_date":
                logger.info(">>> 补完交易日历...")
                backfill_trading_date()

            elif item.name == "sector_data":
                logger.info(">>> 补完板块数据...")
                backfill_sector_data()

            elif item.name == "convertible_bond":
                logger.info(">>> 补完可转债列表 + 日线...")
                backfill_convertible_bond()

            elif item.name == "stock_financial_report" and not skip_financial:
                logger.info(">>> 补完财报数据...")
                backfill_financial(mode="batch")

        except Exception as e:
            logger.error("补完 %s 失败: %s", item.name, e, exc_info=True)


def print_report(report: CompletenessReport):
    """打印完整性报告到控制台。"""
    print(f"\n{'='*70}")
    print(f"  数据完整性报告  {report.checked_at:%Y-%m-%d %H:%M:%S}")
    print(f"{'='*70}\n")

    if not report.issues:
        print("  [OK] 所有数据表完整, 无需补完\n")
        return

    print(f"  发现 {len(report.issues)} 个问题:\n")
    for item in report.issues:
        marker = {1: "!!!", 2: "!! ", 3: "!  ", 4: ".  "}.get(item.priority, "   ")
        print(f"  {marker} [P{item.priority}] {item.name}")
        print(f"       {item.issue}")
        print()

    print(f"{'='*70}\n")


# ====================================================================
# CLI
# ====================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="数据完整性检查与补完")
    parser.add_argument(
        "action",
        choices=["check", "backfill", "all"],
        help="check=仅检查, backfill=仅补完, all=检查+补完",
    )
    parser.add_argument(
        "--skip-financial", action="store_true",
        help="跳过财报补完 (耗时较长)",
    )
    parser.add_argument(
        "--sector-start", default="20250101",
        help="板块数据补完起始日期 (默认 20250101)",
    )
    args = parser.parse_args()

    if args.action in ("check", "all"):
        rpt = check_completeness()
        print_report(rpt)

    if args.action in ("backfill", "all"):
        run_backfill(skip_financial=args.skip_financial)

        if args.action == "all":
            print("\n--- 补完后重新检查 ---")
            rpt2 = check_completeness()
            print_report(rpt2)
