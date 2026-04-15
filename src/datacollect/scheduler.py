"""APScheduler 定时调度 (P2-32d)

轻量级进程内调度器, 支持 cron/interval/date 三种触发模式。
管理数据采集、因子计算、模型训练等定时任务。

技术选型: APScheduler >=3.10 (stable), 不使用 4.x alpha 版。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Optional

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)


class CollectScheduler:
    """采集调度器 — APScheduler 封装"""

    def __init__(self):
        self._scheduler = None
        self._jobs: Dict[str, Any] = {}

    def _ensure_scheduler(self):
        if self._scheduler is not None:
            return
        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
            from apscheduler.triggers.interval import IntervalTrigger

            self._scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
            logger.info("APScheduler 初始化成功")
        except ImportError:
            logger.warning("APScheduler 未安装, 调度功能不可用")

    def add_cron_job(
        self,
        job_id: str,
        func: Callable,
        hour: int,
        minute: int = 0,
        day_of_week: str = "mon-fri",
        **kwargs: Any,
    ) -> bool:
        """添加 cron 定时任务

        Args:
            job_id: 任务唯一标识
            func: 要执行的函数
            hour: 小时 (0-23)
            minute: 分钟 (0-59)
            day_of_week: 星期几 (mon-fri 工作日)
        """
        self._ensure_scheduler()
        if self._scheduler is None:
            return False

        from apscheduler.triggers.cron import CronTrigger
        trigger = CronTrigger(
            hour=hour, minute=minute,
            day_of_week=day_of_week, timezone="Asia/Shanghai",
        )
        job = self._scheduler.add_job(func, trigger, id=job_id, replace_existing=True, **kwargs)
        self._jobs[job_id] = job
        logger.info("Cron 任务已添加: %s (%02d:%02d %s)", job_id, hour, minute, day_of_week)
        return True

    def add_interval_job(
        self,
        job_id: str,
        func: Callable,
        seconds: int = 0,
        minutes: int = 0,
        hours: int = 0,
        **kwargs: Any,
    ) -> bool:
        """添加周期性任务"""
        self._ensure_scheduler()
        if self._scheduler is None:
            return False

        from apscheduler.triggers.interval import IntervalTrigger
        trigger = IntervalTrigger(seconds=seconds, minutes=minutes, hours=hours)
        job = self._scheduler.add_job(func, trigger, id=job_id, replace_existing=True, **kwargs)
        self._jobs[job_id] = job
        logger.info("Interval 任务已添加: %s", job_id)
        return True

    def start(self):
        self._ensure_scheduler()
        if self._scheduler and not self._scheduler.running:
            self._scheduler.start()
            logger.info("采集调度器已启动 (%d 个任务)", len(self._jobs))

    def stop(self):
        if self._scheduler and self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("采集调度器已停止")

    def list_jobs(self) -> list[dict]:
        if self._scheduler is None:
            return []
        return [
            {
                "id": job.id,
                "next_run": str(job.next_run_time),
                "trigger": str(job.trigger),
            }
            for job in self._scheduler.get_jobs()
        ]

    def remove_job(self, job_id: str) -> bool:
        if self._scheduler is None:
            return False
        try:
            self._scheduler.remove_job(job_id)
            self._jobs.pop(job_id, None)
            return True
        except Exception:
            return False
