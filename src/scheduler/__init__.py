"""定时任务调度 — 每日数据同步."""

import schedule
import threading
import time
import traceback

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)

_scheduler_thread: threading.Thread | None = None
_running = False


def job_daily_sync() -> None:
    from src.data.sync import DataSyncManager

    mgr = DataSyncManager()
    mgr.incremental_sync(days_back=settings.scheduler.sync_days_back)


def _safe_run(job_fn, job_name: str) -> None:
    try:
        job_fn()
    except Exception as e:
        tb = traceback.format_exc()
        logger.error("定时任务 [%s] 失败: %s\n%s", job_name, e, tb)


def setup_schedule() -> None:
    cfg = settings.scheduler
    schedule.every().day.at(cfg.daily_sync_time).do(_safe_run, job_daily_sync, "daily_sync")
    logger.info("定时任务已配置: daily_sync @ %s", cfg.daily_sync_time)


def _run_scheduler() -> None:
    global _running
    while _running:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error("调度循环异常: %s", e)
        time.sleep(settings.scheduler.poll_interval_sec)


def start_scheduler() -> None:
    global _scheduler_thread, _running
    if _running:
        logger.warning("调度器已在运行")
        return
    setup_schedule()
    _running = True
    _scheduler_thread = threading.Thread(target=_run_scheduler, daemon=True, name="qt-scheduler")
    _scheduler_thread.start()
    logger.info("调度器已启动")


def stop_scheduler() -> None:
    global _running
    _running = False
    schedule.clear()
    logger.info("调度器已停止")
