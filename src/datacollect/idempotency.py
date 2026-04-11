"""幂等性检查 — 防止 TTL 窗口内重复执行相同采集任务"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from src.common.logger import get_logger
from src.datacollect.models import CollectLog

logger = get_logger(__name__)


class IdempotencyChecker:
    """基于 CollectLog.idempotency_key 做去重。"""

    @staticmethod
    def is_duplicate(session: Session, idempotency_key: str, ttl_hours: int = 24) -> bool:
        """检查 TTL 窗口内是否有相同 idempotency_key 的成功记录。"""
        cutoff = datetime.now() - timedelta(hours=ttl_hours)
        exists = (
            session.query(CollectLog.id)
            .filter(
                CollectLog.idempotency_key == idempotency_key,
                CollectLog.status == "success",
                CollectLog.collected_at >= cutoff,
            )
            .first()
        )
        if exists:
            logger.debug("duplicate detected: idempotency_key=%s", idempotency_key)
        return exists is not None

    @staticmethod
    def record_success(session: Session, idempotency_key: str, task_id: str) -> None:
        """在 CollectLog 中标记任务成功完成 (更新已有记录的 idempotency_key)。"""
        log = (
            session.query(CollectLog)
            .filter(CollectLog.task_id == task_id)
            .first()
        )
        if log is not None:
            log.idempotency_key = idempotency_key
            session.flush()
            logger.debug("recorded idempotency_key=%s for task_id=%s", idempotency_key, task_id)
        else:
            logger.warning("CollectLog not found for task_id=%s, cannot record idempotency_key", task_id)
