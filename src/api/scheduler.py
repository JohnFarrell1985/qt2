"""定时任务调度

后台线程轮询 schedule 库, 执行定时同步/快照任务。
异常不会终止调度线程, 会记录日志并尝试推送 webhook 告警。
"""
import schedule
import time
import threading
import traceback

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)

_scheduler_thread: threading.Thread = None
_running = False


def _safe_run(job_fn, job_name: str):
    """安全执行任务: 捕获一切异常, 不让调度线程崩溃"""
    try:
        job_fn()
    except Exception as e:
        tb = traceback.format_exc()
        logger.error(f"定时任务 [{job_name}] 失败: {e}\n{tb}")
        try:
            from src.api.routers.webhook_router import notify_sync_error
            notify_sync_error(job_name, str(e))
        except Exception:
            pass


def job_daily_sync():
    """每日数据同步"""
    from src.data.sync import DataSyncManager
    mgr = DataSyncManager()
    mgr.incremental_sync(days_back=settings.scheduler.sync_days_back)


def job_model_retrain():
    """模型定期重训"""
    logger.info("模型重训任务触发")


def job_position_snapshot():
    """持仓快照"""
    logger.info("持仓快照任务触发")


def setup_schedule():
    """配置定时任务"""
    cfg = settings.scheduler
    schedule.every().day.at(cfg.daily_sync_time).do(_safe_run, job_daily_sync, "daily_sync")
    schedule.every().day.at(cfg.snapshot_time).do(_safe_run, job_position_snapshot, "position_snapshot")
    schedule.every(cfg.retrain_weeks).weeks.do(_safe_run, job_model_retrain, "model_retrain")
    logger.info("定时任务已配置")


def _run_scheduler():
    global _running
    while _running:
        try:
            schedule.run_pending()
        except Exception as e:
            logger.error(f"调度循环异常: {e}")
        time.sleep(settings.scheduler.poll_interval_sec)


def start_scheduler():
    """启动调度器 (后台守护线程)"""
    global _scheduler_thread, _running
    if _running:
        logger.warning("调度器已在运行")
        return
    setup_schedule()
    _running = True
    _scheduler_thread = threading.Thread(target=_run_scheduler, daemon=True, name="qt-scheduler")
    _scheduler_thread.start()
    logger.info("调度器已启动")


def stop_scheduler():
    """停止调度器"""
    global _running
    _running = False
    schedule.clear()
    logger.info("调度器已停止")
