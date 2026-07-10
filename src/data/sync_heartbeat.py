# -*- coding: utf-8 -*-
"""后台同步心跳: 每 N 秒打日志并对比库内行数增量."""
from __future__ import annotations

import threading
import time
from typing import Callable

from sqlalchemy import text

from src.common.db import get_session
from src.common.logger import get_logger

logger = get_logger(__name__)

# 超过该秒数本阶段无任何表行数增长 → 判定 QMT/当前源无法下载此数据
QMT_STALL_NO_DATA_SEC = 180.0
HEARTBEAT_INTERVAL = 30.0

_DEFAULT_TABLES = (
    "sector_stock",
    "stock_divid_factor",
    "index_weight",
    "convertible_bond",
    "cb_daily",
    "trading_date",
    "stock_financial_report",
    "stock_financial_indicator",
    "factor_values",
    "sector_data",
)


def query_table_counts(tables: tuple[str, ...] = _DEFAULT_TABLES) -> dict[str, int]:
    counts: dict[str, int] = {}
    with get_session() as session:
        for table in tables:
            try:
                n = session.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                counts[table] = int(n or 0)
            except Exception:
                counts[table] = -1
    return counts


class SyncHeartbeat:
    """守护线程: 定期输出阶段 + 表行数 + 相对上次心跳的增量."""

    def __init__(
        self,
        interval_sec: float = 30.0,
        tables: tuple[str, ...] = _DEFAULT_TABLES,
        extra: Callable[[], str] | None = None,
    ):
        self.interval_sec = interval_sec
        self.tables = tables
        self.extra = extra
        self.phase = "starting"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last: dict[str, int] = {}
        self._started_mono = time.monotonic()
        self._beats = 0
        self._phase_started_mono = time.monotonic()
        self._last_progress_mono = time.monotonic()
        self._stall_warned = False

    def set_phase(self, phase: str) -> None:
        self.phase = phase
        self._phase_started_mono = time.monotonic()
        self._last_progress_mono = time.monotonic()
        self._stall_warned = False
        logger.info("[心跳] 阶段切换 -> %s", phase)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="sync-heartbeat", daemon=True)
        self._thread.start()
        logger.info("[心跳] 已启动, 间隔 %.0fs", self.interval_sec)

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3.0)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.wait(self.interval_sec):
            self._beat()

    def beat_now(self) -> None:
        """立即打一条心跳(长阻塞操作前后可用)."""
        self._beat()

    def _beat(self) -> None:
        self._beats += 1
        elapsed = time.monotonic() - self._started_mono
        cur = query_table_counts(self.tables)
        delta = {k: cur.get(k, 0) - self._last.get(k, 0) for k in cur}
        self._last = dict(cur)
        if any(v > 0 for v in delta.values()):
            self._last_progress_mono = time.monotonic()
            self._stall_warned = False
        idle = time.monotonic() - self._last_progress_mono
        if idle >= QMT_STALL_NO_DATA_SEC and not self._stall_warned:
            self._stall_warned = True
            logger.warning(
                "[心跳] 已 %.0fs 无落盘 → 判定 QMT 无法下载 phase=%s, 停止",
                idle, self.phase,
            )
        extra_s = ""
        if self.extra:
            try:
                extra_s = f" | {self.extra()}"
            except Exception as exc:
                extra_s = f" | extra_err={exc}"
        logger.info(
            "[心跳 #%d %.0fs] phase=%s idle=%.0fs counts=%s delta=%s%s",
            self._beats, elapsed, self.phase, idle, cur, delta, extra_s,
        )

    def is_stalled(self) -> bool:
        """本阶段是否已连续超过 QMT_STALL_NO_DATA_SEC 无任何表行数增长."""
        return (time.monotonic() - self._last_progress_mono) >= QMT_STALL_NO_DATA_SEC
