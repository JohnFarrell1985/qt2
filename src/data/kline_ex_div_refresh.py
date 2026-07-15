"""除权除息后前复权 K 线刷新 (WebUI 同步 / 批量维护).

流程:
1. 同步 ``stock_divid_factor`` (QMT)
2. 找出近 N 日有除权事件的标的 + 库内检测到除权跳变的标的
3. 对这些标的 **全量重拉** 前复权日 K (覆盖 MIN~今日), 消除混用旧价
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from sqlalchemy import text

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import Stock

logger = get_logger(__name__)

DEFAULT_EX_DIV_LOOKBACK_DAYS = 7  # 仅刷新近一周除权标的, 避免季报季全市场重拉
DEFAULT_QFQ_HISTORY_FLOOR = "19900101"


def codes_with_recent_ex_date(within_days: int = DEFAULT_EX_DIV_LOOKBACK_DAYS) -> list[str]:
    """``stock_divid_factor`` 中近 N 日有除权除息日的标的."""
    cutoff = date.today() - timedelta(days=within_days)
    today = date.today()
    with get_session() as session:
        rows = session.execute(
            text(
                """
                SELECT DISTINCT code FROM stock_divid_factor
                WHERE ex_date >= :cutoff AND ex_date <= :today
                ORDER BY code
                """
            ),
            {"cutoff": cutoff, "today": today},
        ).fetchall()
    return [r[0] for r in rows]


def codes_with_ex_dividend_gap_in_db(within_days: int = 30) -> list[str]:
    """库内最近 K 线出现除权跳变 (混用未复权历史) 的标的."""
    cutoff = date.today() - timedelta(days=within_days)
    sql = text(
        """
        WITH recent AS (
            SELECT code, trade_date, close, change_pct,
                   LAG(close) OVER (PARTITION BY code ORDER BY trade_date) AS prev_close
            FROM stock_daily
            WHERE trade_date >= :cutoff
        )
        SELECT DISTINCT code FROM recent
        WHERE prev_close IS NOT NULL AND prev_close > 0 AND close > 0
          AND (close / prev_close - 1) * 100 < -:gap
          AND (
                change_pct IS NULL
                OR ABS(change_pct - (close / prev_close - 1) * 100) > :tol
              )
        ORDER BY code
        """
    )
    with get_session() as session:
        rows = session.execute(
            sql,
            {
                "cutoff": cutoff,
                "gap": 12.0,
                "tol": 3.0,
            },
        ).fetchall()
    return [r[0] for r in rows]


def collect_codes_needing_qfq_refresh(
    ex_lookback_days: int = DEFAULT_EX_DIV_LOOKBACK_DAYS,
    gap_scan_days: int = 30,
) -> list[str]:
    """合并除权因子表 + 库内跳变检测, 得到需全量前复权刷新的标的."""
    from_factor = set(codes_with_recent_ex_date(ex_lookback_days))
    from_gap = set(codes_with_ex_dividend_gap_in_db(gap_scan_days))
    codes = sorted(from_factor | from_gap)
    if codes:
        logger.info(
            "除权前复权刷新候选: %d 只 (因子表=%d, 跳变检测=%d)",
            len(codes), len(from_factor), len(from_gap),
        )
    return codes


def build_qfq_refresh_tasks(codes: list[str]) -> list[tuple[str, str, str]]:
    """为指定标的构建全量前复权重拉任务 ``(code, start, end)``."""
    if not codes:
        return []
    from src.data.kline_bulk_sync import kline_per_code_floor

    end_date = datetime.now().strftime("%Y%m%d")
    with get_session() as session:
        meta = {
            r[0]: r[1]
            for r in session.query(Stock.code, Stock.list_date)
            .filter(Stock.code.in_(codes))
            .all()
        }
        min_rows = session.execute(
            text(
                """
                SELECT code, MIN(trade_date) AS d
                FROM stock_daily
                WHERE code = ANY(:codes)
                GROUP BY code
                """
            ),
            {"codes": list(codes)},
        ).fetchall()
    min_m = {r[0]: r[1].strftime("%Y%m%d") if r[1] else None for r in min_rows}

    tasks: list[tuple[str, str, str]] = []
    for code in codes:
        floor = kline_per_code_floor(
            DEFAULT_QFQ_HISTORY_FLOOR,
            meta.get(code),
            min_m.get(code),
        )
        tasks.append((code, floor, end_date))
    return tasks


def sync_divid_factors_incremental(start_days: int = 365) -> int:
    """增量同步除权因子 (自 ``start_days`` 前至今). 需 MiniQMT."""
    from src.data.qmt_extra_sync import QmtExtraSync

    start = (date.today() - timedelta(days=start_days)).strftime("%Y%m%d")
    logger.info("开始同步除权因子 (start=%s)", start)
    return QmtExtraSync().sync_divid_factors(start_time=start)


async def refresh_qfq_klines(
    codes: list[str],
    *,
    source: str = "qmt",
    concurrency: int = 4,
) -> int:
    """对指定标的全量重拉前复权日 K 并 upsert."""
    tasks = build_qfq_refresh_tasks(codes)
    if not tasks:
        return 0
    from src.data import kline_bulk_sync

    kline_bulk_sync._active_source = source  # noqa: SLF001
    kline_bulk_sync.reset_em_cache()
    if source in ("tencent", "auto", "qmt"):
        kline_bulk_sync.reset_qq_session()

    return await kline_bulk_sync._async_download(  # noqa: SLF001
        tasks,
        kline_bulk_sync._fetch_stock_daily,
        kline_bulk_sync._bulk_upsert_stock_daily,
        label="Ex-div qfq refresh",
        concurrency=concurrency,
    )


async def run_ex_div_refresh_pipeline(
    *,
    source: str = "qmt",
    concurrency: int = 4,
    ex_lookback_days: int = DEFAULT_EX_DIV_LOOKBACK_DAYS,
    divid_sync_days: int = 365,
    gap_scan_days: int = 30,
) -> dict[str, int]:
    """除权因子同步 + 前复权 K 线全量刷新 (供 WebUI / CLI)."""
    divid_rows = 0
    try:
        divid_rows = sync_divid_factors_incremental(start_days=divid_sync_days)
    except Exception as exc:  # noqa: BLE001
        logger.warning("除权因子同步失败 (将仅用库内因子+跳变检测): %s", exc)

    codes = collect_codes_needing_qfq_refresh(ex_lookback_days, gap_scan_days)
    kline_rows = 0
    if codes:
        kline_rows = await refresh_qfq_klines(
            codes, source=source, concurrency=concurrency,
        )
    return {
        "divid_rows": divid_rows,
        "ex_div_codes": len(codes),
        "ex_div_kline_rows": kline_rows,
    }
