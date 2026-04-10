"""情绪引擎 ORM 模型

sentiment_daily: 每日情绪汇总 (主表), 固定字段 + JSONB 扩展
sentiment_ingest_log: 情报采集日志 (审计追溯)
"""
from datetime import datetime

from sqlalchemy import (
    Column, String, Float, Integer, Date, DateTime, BigInteger,
    Text, Index, JSON,
)
from sqlalchemy.dialects.postgresql import JSONB

from src.common.db import Base

PortableJSONB = JSON().with_variant(JSONB(), "postgresql")


class SentimentDaily(Base):
    """每日情绪汇总 — 固定结构字段 + JSONB 半结构化字段"""
    __tablename__ = "sentiment_daily"

    trade_date = Column(Date, primary_key=True, comment="交易日期")

    # Layer 1: 量价情绪 (从 stock_daily 计算, 零网络成本)
    ad_ratio = Column(Float, comment="涨跌比 (>1.5乐观, <0.5恐慌)")
    limit_up_count = Column(Integer, comment="涨停家数")
    limit_down_count = Column(Integer, comment="跌停家数")
    burst_rate = Column(Float, comment="炸板率 (0~1)")
    new_high_60d = Column(Integer, comment="60日新高家数")
    new_low_60d = Column(Integer, comment="60日新低家数")
    market_volatility_5d = Column(Float, comment="5日市场波动率")
    market_volatility_20d = Column(Float, comment="20日市场波动率")
    volume_ratio = Column(Float, comment="缩放量强度 (>1.3放量, <0.7缩量)")
    sector_concentration = Column(Float, comment="板块集中度")

    # Layer 3a: akshare 资金数据
    north_net_flow = Column(Float, comment="北向净流入 (亿元)")
    north_cumulative = Column(Float, comment="北向年内累计净流入 (亿元)")
    margin_balance = Column(Float, comment="融资余额 (亿元)")
    margin_balance_change = Column(Float, comment="融资余额日变化 (亿元)")

    # Layer 3a: 衍生品/宏观
    futures_basis = Column(Float, comment="股指期货基差 (%)")
    fx_usdcny = Column(Float, comment="美元兑人民币汇率")

    # Layer 3b: LLM/OpenClaw 数值结果
    news_sentiment_score = Column(Float, comment="新闻情绪评分 (-1~+1)")
    gold_price_usd = Column(Float, comment="黄金价格 (USD/oz)")
    crude_oil_usd = Column(Float, comment="原油价格 (USD/bbl)")
    xueqiu_sentiment = Column(Float, comment="雪球社区情绪 (-1~+1)")

    # 合成指标
    earning_effect = Column(Float, comment="赚钱效应指数 (-1~+1)")
    capital_mood = Column(Float, comment="资金情绪指数 (-1~+1)")
    volatility_mood = Column(Float, comment="波动情绪指数 (-1~+1)")
    sector_heat = Column(Float, comment="板块热度指数 (-1~+1)")
    news_mood = Column(Float, comment="新闻情绪指数 (-1~+1)")
    global_mood = Column(Float, comment="外围情绪指数 (-1~+1)")
    composite_sentiment = Column(Float, comment="合成情绪指数 (-1~+1)")

    # 宏观状态判定
    suggested_state = Column(String(32), comment="系统建议的宏观状态")
    applied_state = Column(String(32), comment="实际生效的宏观状态")
    state_confidence = Column(Float, comment="分类置信度 (0~1)")

    hot_sectors = Column(PortableJSONB, default=list, comment='热门板块列表')
    key_events = Column(PortableJSONB, default=list, comment='关键事件')
    hot_stocks = Column(PortableJSONB, default=list, comment='热门个股')
    extra = Column(PortableJSONB, default=dict, comment='扩展字段')

    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_sentiment_state", "applied_state"),
        Index("idx_sentiment_composite", "composite_sentiment"),
        Index("idx_sentiment_hot_sectors", "hot_sectors", postgresql_using="gin"),
        Index("idx_sentiment_key_events", "key_events", postgresql_using="gin"),
    )

    def to_dict(self) -> dict:
        return {
            "trade_date": self.trade_date.isoformat() if self.trade_date else None,
            "ad_ratio": self.ad_ratio,
            "limit_up_count": self.limit_up_count,
            "limit_down_count": self.limit_down_count,
            "composite_sentiment": self.composite_sentiment,
            "suggested_state": self.suggested_state,
            "applied_state": self.applied_state,
            "state_confidence": self.state_confidence,
            "earning_effect": self.earning_effect,
            "capital_mood": self.capital_mood,
            "volatility_mood": self.volatility_mood,
            "sector_heat": self.sector_heat,
            "news_mood": self.news_mood,
            "global_mood": self.global_mood,
            "hot_sectors": self.hot_sectors,
            "key_events": self.key_events,
        }


class SentimentIngestLog(Base):
    """情报采集日志 — 审计追溯"""
    __tablename__ = "sentiment_ingest_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, comment="交易日期")
    source_name = Column(String(64), nullable=False, comment="数据来源")
    schedule_slot = Column(String(16), comment="采集时间槽")

    raw_data = Column(PortableJSONB, comment="原始采集数据")
    cleaned_data = Column(PortableJSONB, comment="LLM 清洗后的标准 JSON")

    status = Column(String(16), default="success", comment="success/failed/partial")
    error_message = Column(Text, comment="错误信息")
    llm_provider = Column(String(32), comment="使用的 LLM 提供商")
    llm_model = Column(String(64), comment="使用的模型名称")
    llm_tokens_in = Column(Integer, comment="输入 token 数")
    llm_tokens_out = Column(Integer, comment="输出 token 数")
    llm_cost_cny = Column(Float, comment="LLM 调用成本 (元)")
    collected_at = Column(DateTime, comment="采集时间")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_ingest_date_source", "trade_date", "source_name"),
        Index("idx_ingest_status", "status"),
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "trade_date": self.trade_date.isoformat() if self.trade_date else None,
            "source_name": self.source_name,
            "schedule_slot": self.schedule_slot,
            "status": self.status,
            "error_message": self.error_message,
            "llm_provider": self.llm_provider,
            "llm_model": self.llm_model,
            "llm_tokens_in": self.llm_tokens_in,
            "llm_tokens_out": self.llm_tokens_out,
            "llm_cost_cny": self.llm_cost_cny,
            "collected_at": self.collected_at.isoformat() if self.collected_at else None,
        }
