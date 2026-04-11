"""数据采集 ORM 模型

collect_log: 每次采集任务的执行日志, 用于监控和审计
collect_dead_letter: 失败任务死信队列, 支持指数退避重试
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON, Column, String, Float, Integer, BigInteger,
    Text, DateTime, Index,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.common.db import Base


class CollectLog(Base):
    """数据采集执行日志"""
    __tablename__ = "collect_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    task_id = Column(String(64), nullable=False, comment="任务 ID")
    source = Column(String(64), nullable=False, comment="数据来源 (akshare/tushare/...)")
    function_name = Column(String(128), nullable=False, comment="调用的函数名")
    status = Column(String(16), nullable=False, default="success", comment="success/failed")
    records_count = Column(Integer, default=0, comment="采集到的记录数")
    elapsed_ms = Column(Float, comment="耗时 (毫秒)")
    error_message = Column(Text, comment="错误信息")
    metadata_json = Column(Text, comment="附加元数据 (JSON 序列化)")
    idempotency_key = Column(String(16), nullable=True, index=True, comment="幂等键")
    collected_at = Column(DateTime, nullable=False, comment="采集时间")
    created_at = Column(DateTime, default=datetime.now, comment="记录创建时间")

    __table_args__ = (
        Index("idx_collect_log_source_time", "source", "collected_at"),
        Index("idx_collect_log_status", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "source": self.source,
            "function_name": self.function_name,
            "status": self.status,
            "records_count": self.records_count,
            "elapsed_ms": self.elapsed_ms,
            "error_message": self.error_message,
            "idempotency_key": self.idempotency_key,
            "collected_at": self.collected_at.isoformat() if self.collected_at else None,
        }


class CollectDeadLetter(Base):
    """失败采集任务死信队列 — 支持指数退避重试"""
    __tablename__ = "collect_dead_letter"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(100), nullable=False, comment="原始任务 ID")
    source = Column(String(50), nullable=False, comment="数据来源")
    data_type = Column(String(50), nullable=False, default="", comment="数据类型")
    error_type = Column(String(50), nullable=False, comment="错误类别")
    error_msg = Column(Text, comment="错误详情")
    payload = Column(JSON().with_variant(JSONB, "postgresql"), comment="任务参数快照")
    retry_count = Column(Integer, default=0, comment="已重试次数")
    max_retries = Column(Integer, default=3, comment="最大重试次数")
    next_retry_at = Column(DateTime, nullable=True, comment="下次重试时间")
    created_at = Column(DateTime, default=func.now(), comment="入队时间")
    resolved_at = Column(DateTime, nullable=True, comment="解决时间")

    __table_args__ = (
        Index("idx_dl_source", "source"),
        Index("idx_dl_resolved", "resolved_at"),
        Index("idx_dl_next_retry", "next_retry_at"),
    )
