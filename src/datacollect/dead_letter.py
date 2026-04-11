"""死信队列 DAO — 失败采集任务的入队、重试、解决

使用指数退避策略控制重试间隔: next_retry_at = now + base * 2^retry_count
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.common.config import settings
from src.common.logger import get_logger
from src.datacollect.models import CollectDeadLetter

logger = get_logger(__name__)

_CFG = settings.datacollect


class DeadLetterDAO:
    """CollectDeadLetter 数据访问对象。"""

    def __init__(self, backoff_base: float | None = None):
        self._backoff_base = backoff_base if backoff_base is not None else _CFG.dead_letter_backoff_base

    def enqueue(
        self,
        session: Session,
        task_id: str,
        source: str,
        data_type: str,
        error_type: str,
        error_msg: str,
        payload: dict | None = None,
        max_retries: int | None = None,
    ) -> CollectDeadLetter:
        """将失败任务放入死信队列。"""
        effective_max_retries = max_retries if max_retries is not None else _CFG.dead_letter_max_retries
        dl = CollectDeadLetter(
            task_id=task_id,
            source=source,
            data_type=data_type,
            error_type=error_type,
            error_msg=error_msg,
            payload=payload,
            max_retries=effective_max_retries,
            retry_count=0,
            next_retry_at=None,
        )
        session.add(dl)
        session.flush()
        logger.info("dead-letter enqueued task_id=%s source=%s error_type=%s", task_id, source, error_type)
        return dl

    def get_pending(self, session: Session, limit: int | None = None) -> list[CollectDeadLetter]:
        """获取可重试的死信: 未解决 & 未耗尽 & 重试时间已到。"""
        effective_limit = limit if limit is not None else _CFG.dead_letter_pending_limit
        now = datetime.now()
        return (
            session.query(CollectDeadLetter)
            .filter(
                CollectDeadLetter.resolved_at.is_(None),
                CollectDeadLetter.retry_count < CollectDeadLetter.max_retries,
                (CollectDeadLetter.next_retry_at.is_(None)) | (CollectDeadLetter.next_retry_at <= now),
            )
            .order_by(CollectDeadLetter.created_at)
            .limit(effective_limit)
            .all()
        )

    def mark_resolved(self, session: Session, dead_letter_id: int) -> None:
        """标记死信已解决。"""
        dl = session.get(CollectDeadLetter, dead_letter_id)
        if dl is None:
            logger.warning("dead-letter id=%d not found", dead_letter_id)
            return
        dl.resolved_at = datetime.now()
        session.flush()
        logger.info("dead-letter id=%d resolved", dead_letter_id)

    def increment_retry(
        self,
        session: Session,
        dead_letter_id: int,
        next_retry_seconds: float = 0,
    ) -> None:
        """递增重试计数, 设置下次重试时间 (指数退避)。"""
        dl = session.get(CollectDeadLetter, dead_letter_id)
        if dl is None:
            logger.warning("dead-letter id=%d not found", dead_letter_id)
            return

        dl.retry_count += 1

        if next_retry_seconds > 0:
            dl.next_retry_at = datetime.now() + timedelta(seconds=next_retry_seconds)
        else:
            backoff = self._backoff_base * (2 ** dl.retry_count)
            dl.next_retry_at = datetime.now() + timedelta(seconds=backoff)

        session.flush()
        logger.info(
            "dead-letter id=%d retry_count=%d next_retry_at=%s",
            dead_letter_id, dl.retry_count, dl.next_retry_at,
        )

    def get_stats(self, session: Session) -> dict:
        """汇总统计: total / pending / resolved / exhausted。"""
        total = session.query(func.count(CollectDeadLetter.id)).scalar() or 0
        resolved = (
            session.query(func.count(CollectDeadLetter.id))
            .filter(CollectDeadLetter.resolved_at.is_not(None))
            .scalar()
            or 0
        )
        exhausted = (
            session.query(func.count(CollectDeadLetter.id))
            .filter(
                CollectDeadLetter.resolved_at.is_(None),
                CollectDeadLetter.retry_count >= CollectDeadLetter.max_retries,
            )
            .scalar()
            or 0
        )
        pending = total - resolved - exhausted
        return {
            "total": total,
            "pending": pending,
            "resolved": resolved,
            "exhausted": exhausted,
        }
