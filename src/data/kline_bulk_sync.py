"""并发批量下载 A股 + ETF 日K线数据

使用 asyncio + ThreadPoolExecutor 并行调用 akshare, 比单线程快 ~8x。
支持增量同步 (仅补齐缺失日期) 和全量下载。

用法:
    uv run python -m src.data.kline_bulk_sync stock   --days-back 365
    uv run python -m src.data.kline_bulk_sync etf     --days-back 365
    uv run python -m src.data.kline_bulk_sync all     --days-back 365
    uv run python -m src.data.kline_bulk_sync all     --days-back 365 --concurrency 16
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.common.config import settings
from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import ETFDaily, ETFInfo, StockDaily, Stock

logger = get_logger(__name__)

_STOCK_COL_MAP = {
    "日期": "trade_date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "change_pct",
    "涨跌额": "change",
    "换手率": "turnover_rate",
}

_ETF_COL_MAP = {
    "日期": "trade_date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
}


def _safe_float(v: Any) -> float | None:
    try:
        if v is not None and not pd.isna(v):
            return float(v)
    except (TypeError, ValueError):
        pass
    return None


def _safe_date(v: Any) -> date | None:
    try:
        if v is not None and not pd.isna(v):
            if hasattr(v, "date"):
                return v.date()
            return pd.Timestamp(v).date()
    except Exception:
        pass
    return None


# ====================================================================
# 单标的拉取 (在线程池中运行)
# ====================================================================

def _fetch_stock_daily(code: str, start_date: str, end_date: str) -> list[dict]:
    import akshare as ak
    try:
        df = ak.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=start_date, end_date=end_date, adjust="qfq",
        )
    except Exception as e:
        logger.debug("stock %s fetch failed: %s", code, e)
        return []
    if df is None or df.empty:
        return []
    records: list[dict] = []
    for _, row in df.iterrows():
        td = _safe_date(row.get("日期"))
        if td is None:
            continue
        rec = {"code": code, "trade_date": td}
        for cn, db in _STOCK_COL_MAP.items():
            if db == "trade_date":
                continue
            if db == "volume":
                val = row.get(cn)
                rec[db] = int(val) if val is not None and not pd.isna(val) else None
            else:
                rec[db] = _safe_float(row.get(cn))
        records.append(rec)
    return records


def _fetch_etf_daily(code: str, start_date: str, end_date: str) -> list[dict]:
    import akshare as ak
    symbol = code.split(".")[0]
    try:
        df = ak.fund_etf_hist_em(
            symbol=symbol, period="daily",
            start_date=start_date, end_date=end_date, adjust="qfq",
        )
    except Exception as e:
        logger.debug("ETF %s fetch failed: %s", code, e)
        return []
    if df is None or df.empty:
        return []
    records: list[dict] = []
    for _, row in df.iterrows():
        td = _safe_date(row.get("日期"))
        if td is None:
            continue
        rec = {"code": code, "trade_date": td}
        for cn, db in _ETF_COL_MAP.items():
            if db == "trade_date":
                continue
            if db == "volume":
                val = row.get(cn)
                rec[db] = int(val) if val is not None and not pd.isna(val) else None
            else:
                rec[db] = _safe_float(row.get(cn))
        records.append(rec)
    return records


# ====================================================================
# 批量 upsert
# ====================================================================

def _bulk_upsert_stock_daily(records: list[dict], batch_size: int = 2000) -> None:
    if not records:
        return
    with get_session() as session:
        for i in range(0, len(records), batch_size):
            batch = records[i: i + batch_size]
            stmt = insert(StockDaily).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["code", "trade_date"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "amount": stmt.excluded.amount,
                    "amplitude": stmt.excluded.amplitude,
                    "change_pct": stmt.excluded.change_pct,
                    "change": stmt.excluded.change,
                    "turnover_rate": stmt.excluded.turnover_rate,
                },
            )
            session.execute(stmt)


def _bulk_upsert_etf_daily(records: list[dict], batch_size: int = 2000) -> None:
    if not records:
        return
    with get_session() as session:
        for i in range(0, len(records), batch_size):
            batch = records[i: i + batch_size]
            stmt = insert(ETFDaily).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["code", "trade_date"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "amount": stmt.excluded.amount,
                },
            )
            session.execute(stmt)


# ====================================================================
# 异步并发调度
# ====================================================================

async def _async_download(
    tasks: list[tuple[str, str, str]],
    fetch_fn,
    upsert_fn,
    label: str,
    concurrency: int = 8,
    flush_every: int = 200,
):
    """并发下载并定期刷入DB。

    Args:
        tasks: [(code, start_date, end_date), ...]
        fetch_fn: 同步拉取函数 (code, start, end) -> list[dict]
        upsert_fn: 批量入库函数 (records) -> None
        label: 日志标签
        concurrency: 并发数
        flush_every: 每多少个标的刷一次DB
    """
    sem = asyncio.Semaphore(concurrency)
    loop = asyncio.get_event_loop()

    total_records = 0
    total_done = 0
    total_failed = 0
    buffer: list[dict] = []
    t0 = time.time()

    async def _worker(code: str, start: str, end: str):
        nonlocal total_records, total_done, total_failed, buffer
        async with sem:
            await asyncio.sleep(0.05)  # tiny stagger to avoid burst
            try:
                records = await loop.run_in_executor(None, fetch_fn, code, start, end)
            except Exception:
                total_failed += 1
                return
            total_done += 1
            if records:
                buffer.extend(records)
                total_records += len(records)

    n = len(tasks)
    logger.info("[%s] 开始并发下载, %d 个标的, concurrency=%d", label, n, concurrency)

    for batch_start in range(0, n, flush_every):
        batch_end = min(batch_start + flush_every, n)
        batch_tasks = tasks[batch_start:batch_end]

        aws = [_worker(code, s, e) for code, s, e in batch_tasks]
        await asyncio.gather(*aws)

        if buffer:
            upsert_fn(buffer)
            buffer = []

        elapsed = time.time() - t0
        rate = total_done / elapsed if elapsed > 0 else 0
        logger.info(
            "[%s] 进度: %d/%d (%.0f/s), 累计 %d 条, 失败 %d, %.0fs",
            label, batch_end, n, rate, total_records, total_failed, elapsed,
        )

    if buffer:
        upsert_fn(buffer)
        buffer = []

    elapsed = time.time() - t0
    logger.info(
        "[%s] 完成: %d 个标的, %d 条记录, 失败 %d, 耗时 %.0fs",
        label, total_done, total_records, total_failed, elapsed,
    )
    return total_records


# ====================================================================
# 主入口
# ====================================================================

def _get_stock_tasks(days_back: int) -> list[tuple[str, str, str]]:
    """构建股票下载任务列表 (增量: 从各股最后日期开始)"""
    end_date = datetime.now().strftime("%Y%m%d")
    fallback_start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

    with get_session() as session:
        codes = [row[0] for row in session.query(Stock.code).all()]
        max_dates_rows = session.execute(text(
            "SELECT code, MAX(trade_date) FROM stock_daily GROUP BY code"
        )).fetchall()

    max_dates = {row[0]: row[1].strftime("%Y%m%d") for row in max_dates_rows if row[1]}

    tasks = []
    for code in codes:
        start = max_dates.get(code, fallback_start)
        tasks.append((code, start, end_date))
    return tasks


def _get_etf_tasks(days_back: int) -> list[tuple[str, str, str]]:
    """构建ETF下载任务列表 (增量: 从各ETF最后日期开始)"""
    end_date = datetime.now().strftime("%Y%m%d")
    fallback_start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

    with get_session() as session:
        codes = [row[0] for row in session.query(ETFInfo.code).all()]
        max_dates_rows = session.execute(text(
            "SELECT code, MAX(trade_date) FROM etf_daily GROUP BY code"
        )).fetchall()

    max_dates = {row[0]: row[1].strftime("%Y%m%d") for row in max_dates_rows if row[1]}

    tasks = []
    for code in codes:
        start = max_dates.get(code, fallback_start)
        tasks.append((code, start, end_date))
    return tasks


async def run(
    mode: str = "all",
    days_back: int = 365,
    concurrency: int = 8,
):
    total = 0

    if mode in ("stock", "all"):
        tasks = _get_stock_tasks(days_back)
        n = await _async_download(
            tasks, _fetch_stock_daily, _bulk_upsert_stock_daily,
            label="Stock K-line", concurrency=concurrency,
        )
        total += n

    if mode in ("etf", "all"):
        tasks = _get_etf_tasks(days_back)
        n = await _async_download(
            tasks, _fetch_etf_daily, _bulk_upsert_etf_daily,
            label="ETF K-line", concurrency=concurrency,
        )
        total += n

    print(f"\n=== K-line sync complete: {total:,} records ===")  # noqa: T201
    return total


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="并发批量下载 A股+ETF 日K线")
    parser.add_argument(
        "mode", choices=["stock", "etf", "all"],
        help="stock=仅A股, etf=仅ETF, all=全部",
    )
    parser.add_argument("--days-back", type=int, default=365, help="回溯天数 (默认365)")
    parser.add_argument("--concurrency", type=int, default=8, help="并发数 (默认8)")
    args = parser.parse_args()

    asyncio.run(run(mode=args.mode, days_back=args.days_back, concurrency=args.concurrency))
