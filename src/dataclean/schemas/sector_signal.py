"""行业轮动信号抽取 Schema (P2-10)

instructor 将此 Schema 注入 LLM 请求, 从研报/新闻中提取行业轮动线索。
"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class SectorRotation(BaseModel):
    """单个行业轮动信号"""
    sector: str = Field(description="行业名称, 如 '半导体', '新能源', '医药'")
    direction: str = Field(description="看多(bullish) / 看空(bearish) / 中性(neutral)")
    catalyst: str = Field(description="驱动因素, 一句话描述")
    time_horizon: str = Field(description="短期(short) / 中期(medium) / 长期(long)")
    confidence: float = Field(ge=0, le=1, description="置信度 0~1")

    @field_validator("direction", mode="before")
    @classmethod
    def _normalize_direction(cls, v: str) -> str:
        mapping = {"看多": "bullish", "看空": "bearish", "中性": "neutral"}
        return mapping.get(v, v.lower())


class SectorSignalExtraction(BaseModel):
    """行业轮动信号抽取结果"""
    top_sectors: list[SectorRotation] = Field(
        default_factory=list, max_length=10,
        description="看好的行业列表",
    )
    avoid_sectors: list[SectorRotation] = Field(
        default_factory=list, max_length=10,
        description="回避的行业列表",
    )
    macro_context: str = Field(
        default="", max_length=200,
        description="宏观背景一句话描述",
    )
    data_source: str = Field(default="", description="数据来源: 研报/新闻/公告")
