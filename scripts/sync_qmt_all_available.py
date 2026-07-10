# -*- coding: utf-8 -*-
"""一键同步 QMT 可下载的全部数据到 PostgreSQL.

步骤:
1. 建表 (``init_database``)
2. QMT 特色数据 (板块成分/除权因子/转债/指数权重)
3. unified_collect 元数据类 (universe/日历/财务/因子/板块指数/转债)
4. 5分钟 K 线 (``stock_minute``)

MiniQMT 不支持项 (节假日/ETF申赎/IPO) 会跳过并记日志.
**滞停规则**: 仅 QMT; 某阶段连续 3 分钟 (180s) 无任何表落盘 → 停止全流程.

用法::

    uv run python scripts/sync_qmt_all_available.py
    uv run python scripts/sync_qmt_all_available.py --with-minute  # 可选: 含 5 分钟 K 线
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
from datetime import datetime

from src.common import db_batch
from src.common.db import init_database
from src.common.logger import get_logger
from src.data.download_engine import get_default_start
from src.data.parallel_qmt_orchestrator import (
    CollectConfig,
    OrchestratorState,
    dispatch_category,
)
from src.data.qmt_extra_sync import QmtExtraSync
from src.data.sync import DataSyncManager
from src.data.sync_heartbeat import HEARTBEAT_INTERVAL, QMT_STALL_NO_DATA_SEC, SyncHeartbeat

logger = get_logger(__name__)

_QMT_ONLY_CATS = (
    "trading_calendar", "financial", "convertible", "factors", "sector_index",
)


def _run_qmt_only_metadata(hb: SyncHeartbeat) -> bool:
    """仅 QMT、顺序执行; 3 分钟无落盘或本类失败则停止. 返回是否全部成功."""
    cfg = CollectConfig(
        qmt_only=True,
        resume=True,
        financial_start="20000101",
        factor_start="20000101",
        db_stall_warn_sec=QMT_STALL_NO_DATA_SEC,
    )
    logger.info("QMT-only 顺序同步: %s", list(_QMT_ONLY_CATS))

    for cat in _QMT_ONLY_CATS:
        if hb.is_stalled():
            logger.error("全局滞停 %.0fs 无落盘, 停止于进入 %s", QMT_STALL_NO_DATA_SEC, cat)
            return False

        hb.set_phase(f"3/4 qmt_only/{cat}")
        db_batch.reset_upsert_heartbeat()
        db_batch.touch_category_heartbeat(cat)

        state = OrchestratorState(stall_events={cat: threading.Event()})
        stop_ev = threading.Event()

        def _watch_stall() -> None:
            while not stop_ev.wait(10.0):
                idle = db_batch.seconds_since_last_upsert_for_category(cat)
                if idle >= QMT_STALL_NO_DATA_SEC:
                    state.stall_events[cat].set()
                    logger.error(
                        "QMT-only %s: %.0fs 无本类落盘, 触发停止",
                        cat, idle,
                    )
                    return

        watcher = threading.Thread(target=_watch_stall, name=f"stall-{cat}", daemon=True)
        watcher.start()
        try:
            result = dispatch_category(cat, cfg, state)
        finally:
            stop_ev.set()
            watcher.join(timeout=2.0)

        logger.info("QMT-only %s => ok=%s value=%s msg=%s", cat, result.ok, result.value, result.message)
        if not result.ok or hb.is_stalled():
            logger.error("QMT-only: 停止于 %s (失败或 3 分钟无落盘)", cat)
            return False

    return True


def _run_minute_5m() -> dict:
    mgr = DataSyncManager()
    stock_list = mgr.client.get_stock_list_in_sector("沪深A股")
    start = get_default_start("5m")
    end = datetime.now().strftime("%Y%m%d")
    logger.info("同步 5 分钟 K 线: %d 只, %s~%s", len(stock_list), start, end)
    return mgr.sync_specific(
        stock_list,
        data_types=["minute_5m"],
        start_date=start,
        end_date=end,
        incremental=True,
    )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass

    p = argparse.ArgumentParser(description="QMT 可下载数据全量同步")
    p.add_argument("--with-minute", action="store_true", help="启用 5 分钟 K 线同步(默认跳过, 数据量大)")
    p.add_argument("--skip-unified", action="store_true", help="跳过 unified_collect 元数据")
    p.add_argument("--skip-extra", action="store_true", help="跳过 QMT 特色数据(第2步, 已下过可续)")
    p.add_argument("--heartbeat-sec", type=float, default=HEARTBEAT_INTERVAL, help="心跳日志间隔秒")
    args = p.parse_args()

    hb = SyncHeartbeat(interval_sec=args.heartbeat_sec)
    hb.start()

    try:
        hb.set_phase("1/4 init_db")
        logger.info("=== 1/4 建表 ===")
        init_database()

        hb.set_phase("2/4 qmt_extra")
        if args.skip_extra:
            logger.info("=== 2/4 跳过 QMT 特色数据 (--skip-extra) ===")
        else:
            logger.info("=== 2/4 QMT 特色数据 ===")
            extra = QmtExtraSync(on_progress=hb.set_phase).run_all()
            logger.info("qmt_extra_sync => %s", extra)
            hb.beat_now()
            if hb.is_stalled():
                logger.error("第2步后 3 分钟无落盘, 停止")
                return 1

        if not args.skip_unified:
            hb.set_phase("3/4 qmt_only")
            logger.info("=== 3/4 QMT-only 元数据 (3min 无落盘即停) ===")
            if not _run_qmt_only_metadata(hb):
                logger.error("=== QMT-only 同步中止 ===")
                return 1
            hb.beat_now()

        if args.with_minute:
            hb.set_phase("4/4 minute_5m")
            logger.info("=== 4/4 5 分钟 K 线 ===")
            try:
                minute_res = _run_minute_5m()
                logger.info("minute_5m => %s", minute_res)
            except Exception as exc:
                logger.error("5 分钟 K 线同步失败: %s", exc)
        else:
            hb.set_phase("4/4 skip_minute")
            logger.info("=== 4/4 跳过 5 分钟 K 线 (需要时加 --with-minute) ===")

        hb.set_phase("done")
        logger.info("=== QMT 全量同步流程结束 ===")
        hb.beat_now()
        return 0
    finally:
        hb.stop()


if __name__ == "__main__":
    raise SystemExit(main())
