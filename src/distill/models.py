"""蒸馏模块 ORM 模型 (P2-19~21)

存储共识标注结果和飞轮队列。
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, String, Float, DateTime, Integer, BigInteger, Text, Boolean
from sqlalchemy.dialects.postgresql import JSONB

from src.common.db import Base


class DistillLabel(Base):
    """共识标注结果表 (P2-19)"""
    __tablename__ = "distill_labels"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    teacher_a_label = Column(String(20))
    teacher_b_label = Column(String(20))
    consensus_label = Column(String(20), nullable=False)
    judge_model = Column(String(50))
    confidence = Column(Float, default=1.0)
    is_hard = Column(Boolean, default=False, index=True)
    difficulty_score = Column(Float)
    metadata_extra = Column(JSONB)
    created_at = Column(DateTime, default=datetime.now)


class FlywheelQueue(Base):
    """飞轮队列表 (P2-21)"""
    __tablename__ = "flywheel_queue"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    text = Column(Text, nullable=False)
    predicted_probs = Column(JSONB)
    max_confidence = Column(Float)
    processed = Column(Boolean, default=False, index=True)
    created_at = Column(DateTime, default=datetime.now)
