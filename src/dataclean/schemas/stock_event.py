"""个股事件抽取 Schema (P2-33a)

从公告/新闻中提取影响个股价格的事件。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class StockEvent(BaseModel):
    """单个股票事件"""
    code: str = Field(description="股票代码, QMT 格式如 000001.SZ")
    event_type: str = Field(
        description="事件类型: earnings/merger/lawsuit/policy/restructure/dividend/buyback/other",
    )
    description: str = Field(description="事件描述")
    impact: str = Field(description="positive/negative/neutral")
    magnitude: str = Field(description="high/medium/low")
    time_horizon: str = Field(
        default="short",
        description="影响周期: intraday/short(1-5d)/medium(1-3m)/long(3m+)",
    )

    @field_validator("impact", mode="before")
    @classmethod
    def _normalize_impact(cls, v: str) -> str:
        mapping = {"利好": "positive", "利空": "negative", "中性": "neutral"}
        return mapping.get(v, v.lower())


class StockEventExtraction(BaseModel):
    """个股事件抽取结果"""
    events: list[StockEvent] = Field(
        default_factory=list, max_length=20,
        description="个股事件列表",
    )
    market_impact_summary: str = Field(
        default="", max_length=200, description="对市场整体影响总结",
    )
