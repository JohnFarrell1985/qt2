"""全库统一「攒够 N 行再 commit」的批次大小 (与 kline/另类数据对齐).

``parallel_qmt_orchestrator`` 在采集线程内设置 ``_log_upsert_category`` (ContextVar);
``log_upsert_commit`` 会自动刷新**该类**最后落盘时间, 供 120s 无落盘时触发换源/中断.
"""
from __future__ import annotations

import sys
import threading
import time
from collections.abc import Callable
from contextvars import ContextVar, Token

from src.common.logger import get_logger

# 与 ``kline_bulk_sync`` 调度、``alt_data_sync`` 落盘默认一致
DEFAULT_TABLE_UPSERT_FLUSH: int = 200

_log = get_logger(__name__)
_heartbeat_lock = threading.Lock()
# 任意一次批量落盘后更新; 供采集监控判断「是否长时间无写库」
_last_upsert_mono: float = time.monotonic()
# 与 parallel_qmt 采集分类同名 (kline, financial, factors, ...); 同线程多段采集共用
_per_category_upsert_mono: dict[str, float] = {}
_log_upsert_category: ContextVar[str | None] = ContextVar("log_upsert_category", default=None)


def log_upsert_category_set(name: str) -> Token:
    """在 ``wrap`` 开头调用 ``tok = log_upsert_category_set('financial')``, ``finally: log_upsert_category_reset(tok)``."""
    return _log_upsert_category.set(name)


def log_upsert_category_reset(token: Token) -> None:
    _log_upsert_category.reset(token)


def get_log_upsert_category() -> str | None:
    return _log_upsert_category.get()


def touch_category_heartbeat(category: str) -> None:
    """采集线程开始工作时调用, 从此时起计「该类的」无落盘秒数."""
    now = time.monotonic()
    with _heartbeat_lock:
        _per_category_upsert_mono[category] = now


def seconds_since_last_upsert_for_category(category: str) -> float:
    """自该类最后一次有 row>0 的落盘, 或 ``touch_category_heartbeat`` 起经历的**墙钟**秒数.

    **已包含**长 HTTP、重试等待、本机解析/组批等时间 —— 即「到下一次成功本类落盘之间」的整段
    不可见期都算进去; 不是「只算 DB 写 200 行那几毫秒」. 超过 ``db_stall_warn_sec`` 即视数据源/路径不健康.

    若尚未 ``touch``(极少见), 返回 0 以避免误报滞停.
    """
    with _heartbeat_lock:
        t = _per_category_upsert_mono.get(category)
    if t is None:
        return 0.0
    return time.monotonic() - t


def _effective_category(*, data_category: str | None) -> str | None:
    if data_category:
        return data_category
    return get_log_upsert_category()


def log_upsert_commit(
    tag: str,
    row_count: int,
    *,
    data_category: str | None = None,
) -> None:
    """每完成一批 insert/upsert 并 commit 时调用, 打 INFO 并刷新心跳 (全局 + 可选采集类)."""
    global _last_upsert_mono
    if row_count <= 0:
        return
    now = time.monotonic()
    cat = _effective_category(data_category=data_category)
    with _heartbeat_lock:
        _last_upsert_mono = now
        if cat:
            _per_category_upsert_mono[cat] = now
    _log.info("落盘 %s: %d 行", tag, row_count)
    # 与上条一致; flush 保证在 tqdm/多线程下仍能在终端立刻看到(避免仅依赖 StreamHandler 时被冲掉/缓冲)
    print(f"[落盘] {tag}: {row_count} 行", file=sys.stdout, flush=True)


def reset_upsert_heartbeat() -> None:
    """新一轮采集任务开始时调用, 避免将启动前的空窗算成「长时间未落盘」。"""
    global _last_upsert_mono
    with _heartbeat_lock:
        _last_upsert_mono = time.monotonic()
        _per_category_upsert_mono.clear()


def seconds_since_last_upsert_commit() -> float:
    return time.monotonic() - _last_upsert_mono


def buffer_push_flush(
    buf: list[dict],
    rec: dict,
    flush_fn: Callable[[list[dict]], None],
    flush_every: int = DEFAULT_TABLE_UPSERT_FLUSH,
) -> None:
    """追加一行; 达到 ``flush_every`` 时调用 ``flush_fn(buf)`` 并 ``clear`` buf."""
    buf.append(rec)
    if len(buf) >= flush_every:
        flush_fn(buf)
        buf.clear()
