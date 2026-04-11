"""数据采集 ORM 模型

collect_log: 每次采集任务的执行日志, 用于监控和审计
"""
from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Integer, BigInteger,
    Text, DateTime, Index,
)

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
            "collected_at": self.collected_at.isoformat() if self.collected_at else None,
        }
