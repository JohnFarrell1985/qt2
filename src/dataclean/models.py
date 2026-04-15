"""数据清洗 ORM 模型 (P2-33d)

清洗日志表 — 追踪 LLM token 用量、成本、延迟。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, String, Float, DateTime, Integer, BigInteger, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB

from src.common.db import Base


class CleanLog(Base):
    """清洗执行日志 — 每次 LLM 清洗调用记录一行"""
    __tablename__ = "clean_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    schema_name = Column(String(50), nullable=False, comment="使用的 Schema 名称")
    engine = Column(String(30), nullable=False, comment="cleaner 引擎: sentiment/rule/passthrough")
    provider = Column(String(30), comment="LLM 提供商: deepseek/qwen/openai")
    model = Column(String(50), comment="模型名称")
    tokens_in = Column(Integer, default=0, comment="输入 token 数")
    tokens_out = Column(Integer, default=0, comment="输出 token 数")
    tokens_cached = Column(Integer, default=0, comment="缓存 token 数")
    cost_usd = Column(Float, default=0.0, comment="本次调用成本 (USD)")
    latency_ms = Column(Integer, default=0, comment="调用延迟 (毫秒)")
    is_fallback = Column(Boolean, default=False, comment="是否使用了降级方案")
    raw_input_preview = Column(String(500), comment="输入预览 (截断)")
    output_preview = Column(String(500), comment="输出预览 (截断)")
    error = Column(Text, comment="如有错误, 记录错误信息")
    metadata_extra = Column(JSONB, comment="扩展元数据")
    created_at = Column(DateTime, default=datetime.now)
