"""Web UI 日 K 同步 + 挂单结算 (后台任务)。"""
from __future__ import annotations

import asyncio
import threading
import time
from datetime import date, datetime
from typing import Any, Callable, Dict, Optional

from sqlalchemy import text

from src.common.db import get_session
from src.common.logger import get_logger

logger = get_logger(__name__)

DEFAULT_DAYS_BACK = 0  # 0 = 按库内最新交易日自动计算
DEFAULT_CONCURRENCY = 4
DEFAULT_SOURCE = "qmt"
SYNC_BUFFER_DAYS = 3
SYNC_MIN_DAYS = 3
SYNC_MAX_DAYS = 30


def compute_sync_days_back(
    *,
    min_days: int = SYNC_MIN_DAYS,
    buffer_days: int = SYNC_BUFFER_DAYS,
    max_days: int = SYNC_MAX_DAYS,
) -> tuple[int, Optional[str]]:
    """按 ``stock_daily`` / ``etf_daily`` 库内最新日 vs 今天计算回溯自然日.

    Returns:
        (days_back, 库内最新交易日 YYYY-MM-DD; 空表时为 None)
    """
    today = date.today()
    latest: Optional[date] = None
    gaps: list[int] = []

    with get_session() as session:
        for tbl in ("stock_daily", "etf_daily"):
            row = session.execute(text(f"SELECT MAX(trade_date) AS d FROM {tbl}")).scalar()
            if row is None:
                continue
            d = row.date() if isinstance(row, datetime) else row
            if not isinstance(d, date):
                continue
            gaps.append(max(0, (today - d).days))
            if latest is None or d < latest:
                latest = d

    if not gaps:
        return max_days, None

    need = max(gaps) + buffer_days
    days_back = max(min_days, min(need, max_days))
    latest_s = latest.isoformat() if latest else None
    logger.info(
        "WebUI 自动计算 days_back=%d (库内最新=%s, 日历缺口=%d, buffer=%d)",
        days_back, latest_s, max(gaps), buffer_days,
    )
    return days_back, latest_s


class DataSyncService:
    """全局单例: QMT 日 K 增量同步 → 推进模拟日并撮合挂单。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._status: Dict[str, Any] = {"running": False}

    def status(self) -> Dict[str, Any]:
        with self._lock:
            st = dict(self._status)
            if st.get("running"):
                st["elapsed"] = round(time.time() - st.get("started", time.time()), 1)
            return st

    def _set(self, **kwargs) -> None:
        with self._lock:
            self._status.update(kwargs)

    def start(
        self,
        on_settle: Callable[[], Dict[str, Any]],
        *,
        days_back: int = DEFAULT_DAYS_BACK,
        concurrency: int = DEFAULT_CONCURRENCY,
        source: str = DEFAULT_SOURCE,
    ) -> Dict[str, Any]:
        auto = days_back <= 0
        if auto:
            effective_days, db_latest = compute_sync_days_back()
        else:
            effective_days = max(1, min(int(days_back), 365))
            db_latest = None
        with self._lock:
            if self._status.get("running"):
                return {"ok": False, "detail": "数据同步任务进行中"}
            self._status = {
                "running": True,
                "phase": "etf",
                "started": time.time(),
                "elapsed": 0.0,
                "days_back": effective_days,
                "days_back_auto": auto,
                "db_latest": db_latest,
                "source": source,
                "concurrency": concurrency,
                "etf_rows": 0,
                "stock_rows": 0,
                "error": None,
                "settled": None,
                "latest": None,
            }
        t = threading.Thread(
            target=self._run,
            args=(on_settle, effective_days, concurrency, source),
            daemon=True,
        )
        t.start()
        return {"ok": True, "days_back": effective_days, "db_latest": db_latest}

    def _run(
        self,
        on_settle: Callable[[], Dict[str, Any]],
        days_back: int,
        concurrency: int,
        source: str,
    ) -> None:
        t0 = time.time()
        etf_rows = stock_rows = 0
        try:
            from src.data import kline_bulk_sync

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                self._set(phase="etf")
                logger.info("WebUI 开始同步 ETF 日K (days_back=%d source=%s)", days_back, source)
                etf_rows = loop.run_until_complete(
                    kline_bulk_sync.run(
                        mode="etf",
                        days_back=days_back,
                        source=source,
                        concurrency=concurrency,
                        resume=True,
                        fill_interior_gaps=False,
                    )
                )
                self._set(phase="stock", etf_rows=int(etf_rows or 0))

                logger.info("WebUI 开始同步 A 股日K (days_back=%d source=%s)", days_back, source)
                stock_rows = loop.run_until_complete(
                    kline_bulk_sync.run(
                        mode="stock",
                        days_back=days_back,
                        source=source,
                        concurrency=concurrency,
                        resume=True,
                        fill_interior_gaps=False,
                    )
                )
                self._set(phase="ex_div", stock_rows=int(stock_rows or 0))

                logger.info("WebUI 开始除权因子 + 前复权刷新 (source=%s)", source)
                from src.data.kline_ex_div_refresh import run_ex_div_refresh_pipeline

                ex_div_stats = loop.run_until_complete(
                    run_ex_div_refresh_pipeline(
                        source=source,
                        concurrency=concurrency,
                    )
                )
                self._set(
                    phase="settle",
                    divid_rows=int(ex_div_stats.get("divid_rows", 0)),
                    ex_div_codes=int(ex_div_stats.get("ex_div_codes", 0)),
                    ex_div_kline_rows=int(ex_div_stats.get("ex_div_kline_rows", 0)),
                )
            finally:
                loop.close()

            settled = on_settle()
            latest = None
            if settled:
                first = next(iter(settled.values()), {})
                latest = first.get("latest")
            self._set(
                running=False,
                phase="done",
                elapsed=round(time.time() - t0, 1),
                etf_rows=int(etf_rows or 0),
                stock_rows=int(stock_rows or 0),
                settled=settled,
                latest=latest,
                error=None,
            )
            logger.info(
                "WebUI 数据同步完成: etf=%d stock=%d ex_div_codes=%s ex_div_kline=%s latest=%s elapsed=%.1fs",
                etf_rows,
                stock_rows,
                self._status.get("ex_div_codes"),
                self._status.get("ex_div_kline_rows"),
                latest,
                time.time() - t0,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception("WebUI 数据同步失败: %s", e)
            self._set(
                running=False,
                phase="error",
                elapsed=round(time.time() - t0, 1),
                etf_rows=int(etf_rows or 0),
                stock_rows=int(stock_rows or 0),
                error=str(e),
            )


_service: Optional[DataSyncService] = None
_service_lock = threading.Lock()


def get_data_sync_service() -> DataSyncService:
    global _service
    with _service_lock:
        if _service is None:
            _service = DataSyncService()
        return _service
