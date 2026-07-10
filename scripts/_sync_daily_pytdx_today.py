"""一次性 pytdx 日线同步 — 东财/腾讯不可用时兜底."""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

from pytdx.hq import TdxHq_API
from sqlalchemy import text

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.kline_bulk_sync import _bulk_upsert_etf_daily, _bulk_upsert_stock_daily

logger = get_logger(__name__)

SERVERS = [
    ("218.75.126.9", 7709),
    ("119.147.212.81", 7709),
    ("114.80.63.12", 7709),
]


def _market(code: str) -> int:
    pure = code.split(".")[0]
    if pure.startswith(("6", "5", "9")):
        return 1
    return 0


def _bar_to_stock_record(code: str, bar: dict, prev_close: float | None) -> dict:
    td = date(int(bar["year"]), int(bar["month"]), int(bar["day"]))
    close = float(bar["close"])
    chg = (close - prev_close) if prev_close else None
    pct = (chg / prev_close * 100) if chg and prev_close else None
    high = float(bar["high"])
    low = float(bar["low"])
    amp = ((high - low) / prev_close * 100) if prev_close else None
    return {
        "code": code,
        "trade_date": td,
        "open": float(bar["open"]),
        "high": high,
        "low": low,
        "close": close,
        "volume": int(bar["vol"]),
        "amount": float(bar["amount"]),
        "change": chg,
        "change_pct": pct,
        "amplitude": amp,
        "turnover_rate": None,
    }


def _bar_to_etf_record(code: str, bar: dict) -> dict:
    return {
        "code": code,
        "trade_date": date(int(bar["year"]), int(bar["month"]), int(bar["day"])),
        "open": float(bar["open"]),
        "high": float(bar["high"]),
        "low": float(bar["low"]),
        "close": float(bar["close"]),
        "volume": int(bar["vol"]),
        "amount": float(bar["amount"]),
    }


def _fetch_stock_bars(api: TdxHq_API, code: str, market: int, cutoff: date) -> list[dict]:
    bars = api.get_security_bars(9, market, code, 0, 30)
    if not bars:
        return []
    records: list[dict] = []
    prev_close: float | None = None
    for bar in sorted(bars, key=lambda b: (b["year"], b["month"], b["day"])):
        td = date(int(bar["year"]), int(bar["month"]), int(bar["day"]))
        if td < cutoff:
            prev_close = float(bar["close"])
            continue
        records.append(_bar_to_stock_record(code, bar, prev_close))
        prev_close = float(bar["close"])
    return records


def _fetch_etf_bars(api: TdxHq_API, code: str, market: int, cutoff: date) -> list[dict]:
    bars = api.get_security_bars(9, market, code, 0, 30)
    if not bars:
        return []
    return [
        _bar_to_etf_record(code, bar)
        for bar in sorted(bars, key=lambda b: (b["year"], b["month"], b["day"]))
        if date(int(bar["year"]), int(bar["month"]), int(bar["day"])) >= cutoff
    ]


def _connect() -> TdxHq_API:
    api = TdxHq_API()
    for host, port in SERVERS:
        try:
            if api.connect(host, port):
                logger.info("pytdx connected %s:%s", host, port)
                return api
        except Exception as e:
            logger.warning("pytdx connect failed %s:%s %s", host, port, e)
    raise RuntimeError("pytdx 全部服务器连接失败")


def sync_table(api: TdxHq_API, table: str, cutoff: date) -> tuple[int, int]:
    with get_session() as s:
        codes = [r[0] for r in s.execute(text(f"SELECT code FROM {table} ORDER BY code")).fetchall()]
    total = len(codes)
    ok = fail = inserted = 0
    batch: list[dict] = []
    is_stock = table == "stocks"
    upsert = _bulk_upsert_stock_daily if is_stock else _bulk_upsert_etf_daily
    fetch_fn = _fetch_stock_bars if is_stock else _fetch_etf_bars

    for i, code in enumerate(codes, 1):
        try:
            recs = fetch_fn(api, code, _market(code), cutoff)
            batch.extend(recs)
            ok += 1
        except Exception as e:
            fail += 1
            if fail <= 5:
                logger.warning("fetch %s failed: %s", code, e)
        if len(batch) >= 500:
            upsert(batch)
            inserted += len(batch)
            batch.clear()
        if i % 500 == 0:
            logger.info("[%s] %d/%d ok=%d fail=%d inserted=%d", table, i, total, ok, fail, inserted)

    if batch:
        upsert(batch)
        inserted += len(batch)
    return ok, inserted


def main() -> int:
    cutoff = (datetime.now() - timedelta(days=15)).date()
    today = date.today()
    logger.info("pytdx daily sync cutoff=%s today=%s", cutoff, today)

    api = _connect()
    try:
        stock_ok, stock_n = sync_table(api, "stocks", cutoff)
        etf_ok, etf_n = sync_table(api, "etf_info", cutoff)
    finally:
        api.disconnect()

    with get_session() as s:
        for tbl, label in [("stock_daily", "A股"), ("etf_daily", "ETF")]:
            r = s.execute(
                text(
                    "SELECT MAX(trade_date), COUNT(DISTINCT code) FILTER (WHERE trade_date=:t) "
                    f"FROM {tbl}"
                ),
                {"t": today},
            ).fetchone()
            print(f"{label}: max_date={r[0]}, today_codes={r[1]}")

    print(f"done: stocks ok={stock_ok} rows={stock_n}, etf ok={etf_ok} rows={etf_n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
