"""并发批量下载 A股 + ETF + 指数 日K线数据

多数据源自动降级:
  1. 东方财富 (curl_cffi + Chrome指纹 + UA轮换 + 令牌桶限流)
  2. 腾讯财经 (requests 直连, OHLCV)

用法:
    uv run python -m src.data.kline_bulk_sync stock   --days-back 365
    uv run python -m src.data.kline_bulk_sync etf     --days-back 365
    uv run python -m src.data.kline_bulk_sync index   --days-back 365
    uv run python -m src.data.kline_bulk_sync all     --days-back 365 --concurrency 8
    uv run python -m src.data.kline_bulk_sync all     --days-back 365 --source tencent
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import ETFDaily, ETFInfo, MarketIndex, StockDaily, Stock

logger = get_logger(__name__)

INDEX_NAME_MAP: dict[str, str] = {
    "000001": "上证综指",
    "399001": "深证成指",
    "000300": "沪深300",
    "000905": "中证500",
    "000852": "中证1000",
    "399006": "创业板指",
    "000688": "科创50",
}

# ==================================================================
# 数据源 1: 东方财富 (完整字段, 需反反爬)
# ==================================================================
_EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_EM_FIELDS1 = "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
_EM_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"

_em_client = None
_em_limiter = None


def _get_em_client():
    global _em_client
    if _em_client is None:
        from src.datacollect.client import SmartHttpClient
        _em_client = SmartHttpClient()
    return _em_client


def _get_em_limiter(rate: float = 3.0, burst: int = 5):
    global _em_limiter
    if _em_limiter is None:
        from src.datacollect.rate_limiter import TokenBucketLimiter
        _em_limiter = TokenBucketLimiter.for_domain(
            "eastmoney_bulk", rate=rate, burst=burst,
        )
    return _em_limiter


def _em_stock_secid(code: str) -> str:
    return f"1.{code}" if code.startswith("6") else f"0.{code}"


def _em_etf_secid(code: str) -> str:
    pure = code.split(".")[0]
    prefix = pure[:2]
    if prefix in ("51", "58", "56", "52", "53"):
        return f"1.{pure}"
    return f"0.{pure}"


def _em_index_secid(code: str) -> str:
    return f"0.{code}" if code.startswith("399") else f"1.{code}"


def _em_fetch_kline(secid: str, start_date: str, end_date: str) -> list[list[str]]:
    """东方财富 K线 API, 返回原始行 [date, open, close, high, low, vol, amount, amp, pct, chg, turnover]."""
    limiter = _get_em_limiter()
    limiter.acquire()
    client = _get_em_client()
    params = {
        "secid": secid, "klt": "101", "fqt": "1", "lmt": "0",
        "beg": start_date, "end": end_date,
        "fields1": _EM_FIELDS1, "fields2": _EM_FIELDS2,
    }
    resp = client.get(_EM_KLINE_URL, params=params)
    body: dict = resp.json()
    if body.get("rc") not in (0, None):
        return []
    klines = body.get("data", {}).get("klines") or []
    return [line.split(",")[:11] for line in klines if len(line.split(",")) >= 11]


# ==================================================================
# 数据源 2: 腾讯财经 (OHLCV, 无需反爬)
# ==================================================================
_QQ_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

_qq_session = None
_qq_limiter = None


def _get_qq_session():
    """requests Session with no proxy."""
    global _qq_session
    if _qq_session is None:
        import requests
        _qq_session = requests.Session()
        _qq_session.trust_env = False
        _qq_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://stockapp.finance.qq.com/",
        })
    return _qq_session


def _get_qq_limiter(rate: float = 10.0, burst: int = 15):
    """腾讯财经限流: 默认 10 req/s, burst=15 (宽松但有保护)."""
    global _qq_limiter
    if _qq_limiter is None:
        from src.datacollect.rate_limiter import TokenBucketLimiter
        _qq_limiter = TokenBucketLimiter.for_domain(
            "tencent_finance", rate=rate, burst=burst,
        )
    return _qq_limiter


def _qq_symbol(code: str, asset_type: str = "stock") -> str:
    """Convert code to Tencent symbol format (sh/sz prefix)."""
    pure = code.split(".")[0]
    if asset_type == "index":
        return f"sz{pure}" if pure.startswith("399") else f"sh{pure}"
    if pure.startswith(("6", "5", "9")):
        return f"sh{pure}"
    return f"sz{pure}"


def _qq_fetch_kline(symbol: str, start_date: str, end_date: str) -> list[list[str]]:
    """腾讯财经 K线 API, 返回 [date, open, close, high, low, volume]."""
    _get_qq_limiter().acquire()
    s_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
    e_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
    session = _get_qq_session()
    resp = session.get(
        _QQ_KLINE_URL,
        params={"param": f"{symbol},day,{s_fmt},{e_fmt},500,qfq"},
        timeout=15,
    )
    body = resp.json()
    data = body.get("data", {})
    if not data:
        return []
    sym_data = data.get(symbol, {})
    rows = sym_data.get("day") or sym_data.get("qfqday") or []
    return rows


# ==================================================================
# 辅助函数
# ==================================================================

def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _safe_date(v: str) -> date | None:
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# ==================================================================
# 健康探测: 检测 eastmoney 是否可达
# ==================================================================
_em_healthy: bool | None = None


def _probe_em() -> bool:
    """探测 push2his.eastmoney.com 是否可用 (缓存结果)。"""
    global _em_healthy
    if _em_healthy is not None:
        return _em_healthy
    try:
        client = _get_em_client()
        _get_em_limiter().acquire()
        resp = client.get(
            _EM_KLINE_URL,
            params={
                "secid": "1.000300", "klt": "101", "fqt": "1",
                "lmt": "0", "beg": "20260410", "end": "20260413",
                "fields1": _EM_FIELDS1, "fields2": _EM_FIELDS2,
            },
        )
        body = resp.json()
        _em_healthy = body.get("rc") in (0, None)
    except Exception as e:
        logger.warning("东方财富探测失败, 将使用腾讯数据源: %s", e)
        _em_healthy = False
    logger.info("东方财富可达: %s", _em_healthy)
    return _em_healthy


# ==================================================================
# 标的拉取 (线程池中运行) — 自动选择数据源
# ==================================================================

def _fetch_stock_daily(code: str, start_date: str, end_date: str) -> list[dict]:
    source = _active_source
    if source == "auto":
        source = "eastmoney" if _probe_em() else "tencent"

    if source == "eastmoney":
        return _em_fetch_stock(code, start_date, end_date)
    return _qq_fetch_stock(code, start_date, end_date)


def _fetch_etf_daily(code: str, start_date: str, end_date: str) -> list[dict]:
    source = _active_source
    if source == "auto":
        source = "eastmoney" if _probe_em() else "tencent"

    if source == "eastmoney":
        return _em_fetch_etf(code, start_date, end_date)
    return _qq_fetch_etf(code, start_date, end_date)


def _fetch_index_daily(code: str, start_date: str, end_date: str) -> list[dict]:
    source = _active_source
    if source == "auto":
        source = "eastmoney" if _probe_em() else "tencent"

    if source == "eastmoney":
        return _em_fetch_index(code, start_date, end_date)
    return _qq_fetch_index(code, start_date, end_date)


_active_source: str = "auto"


# -- Eastmoney 实现 --

def _em_fetch_stock(code: str, start_date: str, end_date: str) -> list[dict]:
    rows = _em_fetch_kline(_em_stock_secid(code), start_date, end_date)
    records: list[dict] = []
    for p in rows:
        td = _safe_date(p[0])
        if not td:
            continue
        records.append({
            "code": code, "trade_date": td,
            "open": _safe_float(p[1]), "close": _safe_float(p[2]),
            "high": _safe_float(p[3]), "low": _safe_float(p[4]),
            "volume": _safe_int(p[5]), "amount": _safe_float(p[6]),
            "amplitude": _safe_float(p[7]), "change_pct": _safe_float(p[8]),
            "change": _safe_float(p[9]), "turnover_rate": _safe_float(p[10]),
        })
    return records


def _em_fetch_etf(code: str, start_date: str, end_date: str) -> list[dict]:
    rows = _em_fetch_kline(_em_etf_secid(code), start_date, end_date)
    records: list[dict] = []
    for p in rows:
        td = _safe_date(p[0])
        if not td:
            continue
        records.append({
            "code": code, "trade_date": td,
            "open": _safe_float(p[1]), "close": _safe_float(p[2]),
            "high": _safe_float(p[3]), "low": _safe_float(p[4]),
            "volume": _safe_int(p[5]), "amount": _safe_float(p[6]),
        })
    return records


def _em_fetch_index(code: str, start_date: str, end_date: str) -> list[dict]:
    rows = _em_fetch_kline(_em_index_secid(code), start_date, end_date)
    index_name = INDEX_NAME_MAP.get(code, code)
    records: list[dict] = []
    prev_close: float | None = None
    for p in rows:
        td = _safe_date(p[0])
        if not td:
            continue
        close_val = _safe_float(p[2])
        chg = (close_val - prev_close) if close_val and prev_close else None
        pct = (chg / prev_close * 100) if chg and prev_close else None
        records.append({
            "index_code": code, "index_name": index_name, "trade_date": td,
            "open": _safe_float(p[1]), "close": close_val,
            "high": _safe_float(p[3]), "low": _safe_float(p[4]),
            "volume": _safe_int(p[5]), "amount": _safe_float(p[6]),
            "change": chg, "change_pct": pct,
        })
        prev_close = close_val
    return records


# -- Tencent 实现 --

def _qq_fetch_stock(code: str, start_date: str, end_date: str) -> list[dict]:
    symbol = _qq_symbol(code, "stock")
    rows = _qq_fetch_kline(symbol, start_date, end_date)
    records: list[dict] = []
    prev_close: float | None = None
    for p in rows:
        td = _safe_date(p[0])
        if not td:
            continue
        close_val = _safe_float(p[2])
        chg = (close_val - prev_close) if close_val and prev_close else None
        pct = (chg / prev_close * 100) if chg and prev_close else None
        records.append({
            "code": code, "trade_date": td,
            "open": _safe_float(p[1]), "close": close_val,
            "high": _safe_float(p[3]), "low": _safe_float(p[4]),
            "volume": _safe_int(p[5]), "amount": None,
            "amplitude": None, "change_pct": pct,
            "change": chg, "turnover_rate": None,
        })
        prev_close = close_val
    return records


def _qq_fetch_etf(code: str, start_date: str, end_date: str) -> list[dict]:
    pure = code.split(".")[0]
    symbol = _qq_symbol(pure, "stock")
    rows = _qq_fetch_kline(symbol, start_date, end_date)
    records: list[dict] = []
    for p in rows:
        td = _safe_date(p[0])
        if not td:
            continue
        records.append({
            "code": code, "trade_date": td,
            "open": _safe_float(p[1]), "close": _safe_float(p[2]),
            "high": _safe_float(p[3]), "low": _safe_float(p[4]),
            "volume": _safe_int(p[5]), "amount": None,
        })
    return records


def _qq_fetch_index(code: str, start_date: str, end_date: str) -> list[dict]:
    symbol = _qq_symbol(code, "index")
    rows = _qq_fetch_kline(symbol, start_date, end_date)
    index_name = INDEX_NAME_MAP.get(code, code)
    records: list[dict] = []
    prev_close: float | None = None
    for p in rows:
        td = _safe_date(p[0])
        if not td:
            continue
        close_val = _safe_float(p[2])
        chg = (close_val - prev_close) if close_val and prev_close else None
        pct = (chg / prev_close * 100) if chg and prev_close else None
        records.append({
            "index_code": code, "index_name": index_name, "trade_date": td,
            "open": _safe_float(p[1]), "close": close_val,
            "high": _safe_float(p[3]), "low": _safe_float(p[4]),
            "volume": _safe_int(p[5]), "amount": None,
            "change": chg, "change_pct": pct,
        })
        prev_close = close_val
    return records


# ==================================================================
# 批量 upsert
# ==================================================================

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


def _bulk_upsert_index_daily(records: list[dict], batch_size: int = 2000) -> None:
    if not records:
        return
    with get_session() as session:
        for i in range(0, len(records), batch_size):
            batch = records[i: i + batch_size]
            stmt = insert(MarketIndex).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["index_code", "trade_date"],
                set_={
                    "index_name": stmt.excluded.index_name,
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "amount": stmt.excluded.amount,
                    "change": stmt.excluded.change,
                    "change_pct": stmt.excluded.change_pct,
                },
            )
            session.execute(stmt)


# ==================================================================
# 异步并发调度
# ==================================================================

async def _async_download(
    tasks: list[tuple[str, str, str]],
    fetch_fn,
    upsert_fn,
    label: str,
    concurrency: int = 8,
    flush_every: int = 200,
):
    sem = asyncio.Semaphore(concurrency)
    loop = asyncio.get_running_loop()

    total_records = 0
    total_done = 0
    total_failed = 0
    buffer: list[dict] = []
    t0 = time.time()

    async def _worker(code: str, start: str, end: str):
        nonlocal total_records, total_done, total_failed, buffer
        async with sem:
            await asyncio.sleep(0.02)
            try:
                records = await loop.run_in_executor(None, fetch_fn, code, start, end)
            except Exception as e:
                total_failed += 1
                logger.debug("[%s] %s failed: %s", label, code, e)
                return
            total_done += 1
            if records:
                buffer.extend(records)
                total_records += len(records)

    n = len(tasks)
    logger.info("[%s] 开始并发下载, %d 个标的, concurrency=%d, source=%s",
                label, n, concurrency, _active_source)

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
            "[%s] 进度: %d/%d (%.1f/s), 累计 %d 条, 失败 %d, %.0fs",
            label, batch_end, n, rate, total_records, total_failed, elapsed,
        )

    if buffer:
        upsert_fn(buffer)

    elapsed = time.time() - t0
    logger.info(
        "[%s] 完成: %d 个标的, %d 条记录, 失败 %d, 耗时 %.0fs",
        label, total_done, total_records, total_failed, elapsed,
    )
    return total_records


# ==================================================================
# 任务构建
# ==================================================================

def _get_stock_tasks(days_back: int) -> list[tuple[str, str, str]]:
    end_date = datetime.now().strftime("%Y%m%d")
    fallback_start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

    with get_session() as session:
        codes = [row[0] for row in session.query(Stock.code).all()]
        max_dates_rows = session.execute(text(
            "SELECT code, MAX(trade_date) FROM stock_daily GROUP BY code"
        )).fetchall()

    max_dates = {row[0]: row[1].strftime("%Y%m%d") for row in max_dates_rows if row[1]}
    return [(code, max_dates.get(code, fallback_start), end_date) for code in codes]


def _get_etf_tasks(days_back: int) -> list[tuple[str, str, str]]:
    end_date = datetime.now().strftime("%Y%m%d")
    fallback_start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

    with get_session() as session:
        codes = [row[0] for row in session.query(ETFInfo.code).all()]
        max_dates_rows = session.execute(text(
            "SELECT code, MAX(trade_date) FROM etf_daily GROUP BY code"
        )).fetchall()

    max_dates = {row[0]: row[1].strftime("%Y%m%d") for row in max_dates_rows if row[1]}
    return [(code, max_dates.get(code, fallback_start), end_date) for code in codes]


def _get_index_tasks(days_back: int) -> list[tuple[str, str, str]]:
    end_date = datetime.now().strftime("%Y%m%d")
    fallback_start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

    with get_session() as session:
        max_dates_rows = session.execute(text(
            "SELECT index_code, MAX(trade_date) FROM market_index GROUP BY index_code"
        )).fetchall()

    max_dates = {row[0]: row[1].strftime("%Y%m%d") for row in max_dates_rows if row[1]}
    return [(code, max_dates.get(code, fallback_start), end_date) for code in INDEX_NAME_MAP]


# ==================================================================
# 主入口
# ==================================================================

async def run(
    mode: str = "all",
    days_back: int = 365,
    concurrency: int = 8,
    source: str = "auto",
    rate: float = 3.0,
    burst: int = 5,
):
    global _active_source
    _active_source = source

    if source in ("eastmoney", "auto"):
        _get_em_limiter(rate=rate, burst=burst)

    total = 0

    if mode in ("stock", "all"):
        tasks = _get_stock_tasks(days_back)
        total += await _async_download(
            tasks, _fetch_stock_daily, _bulk_upsert_stock_daily,
            label="Stock K-line", concurrency=concurrency,
        )

    if mode in ("etf", "all"):
        tasks = _get_etf_tasks(days_back)
        total += await _async_download(
            tasks, _fetch_etf_daily, _bulk_upsert_etf_daily,
            label="ETF K-line", concurrency=concurrency,
        )

    if mode in ("index", "all"):
        tasks = _get_index_tasks(days_back)
        total += await _async_download(
            tasks, _fetch_index_daily, _bulk_upsert_index_daily,
            label="Index K-line", concurrency=concurrency,
        )

    print(f"\n=== K-line sync complete: {total:,} records ===")  # noqa: T201
    return total


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="并发批量下载 A股+ETF+指数 日K线")
    parser.add_argument(
        "mode", choices=["stock", "etf", "index", "all"],
        help="stock=A股, etf=ETF, index=指数, all=全部",
    )
    parser.add_argument("--days-back", type=int, default=365, help="回溯天数 (默认365)")
    parser.add_argument("--concurrency", type=int, default=8, help="并发线程数 (默认8)")
    parser.add_argument(
        "--source", choices=["auto", "eastmoney", "tencent"], default="auto",
        help="数据源: auto=自动探测降级, eastmoney=东财, tencent=腾讯 (默认auto)",
    )
    parser.add_argument("--rate", type=float, default=3.0, help="东财限流速率 req/s")
    parser.add_argument("--burst", type=int, default=5, help="东财限流突发上限")
    args = parser.parse_args()

    asyncio.run(run(
        mode=args.mode,
        days_back=args.days_back,
        concurrency=args.concurrency,
        source=args.source,
        rate=args.rate,
        burst=args.burst,
    ))
