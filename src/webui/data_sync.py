"""Web UI 日 K 同步 + 挂单结算 (后台任务)。"""
from __future__ import annotations

import asyncio
import threading
import time
from typing import Any, Callable, Dict, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)

DEFAULT_DAYS_BACK = 15
DEFAULT_CONCURRENCY = 4
DEFAULT_SOURCE = "qmt"


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
        with self._lock:
            if self._status.get("running"):
                return {"ok": False, "detail": "数据同步任务进行中"}
            self._status = {
                "running": True,
                "phase": "etf",
                "started": time.time(),
                "elapsed": 0.0,
                "days_back": days_back,
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
            args=(on_settle, days_back, concurrency, source),
            daemon=True,
        )
        t.start()
        return {"ok": True}

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
                    )
                )
                self._set(phase="settle", stock_rows=int(stock_rows or 0))
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
                "WebUI 数据同步完成: etf=%d stock=%d latest=%s elapsed=%.1fs",
                etf_rows, stock_rows, latest, time.time() - t0,
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
