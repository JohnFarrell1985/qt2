"""宏观经济指标抽取 Schema (P2-12)

从央行公告/统计局数据/财经新闻中提取宏观经济数据。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class MacroDataPoint(BaseModel):
    """单个宏观数据点"""
    indicator: str = Field(description="指标名称, 如 'CPI', 'PMI', 'M2'")
    value: float = Field(description="数值")
    unit: str = Field(default="%", description="单位")
    period: str = Field(default="", description="统计周期, 如 '2026-03'")
    direction: str = Field(default="", description="环比方向: up/down/flat")
    expectation: str = Field(
        default="", description="vs 市场预期: above/below/inline",
    )


class MacroIndicatorExtraction(BaseModel):
    """宏观经济指标抽取结果"""
    indicators: list[MacroDataPoint] = Field(
        default_factory=list, max_length=20,
        description="宏观指标列表",
    )
    policy_signal: str = Field(
        default="neutral",
        description="政策信号: easing(宽松) / tightening(紧缩) / neutral(中性)",
    )
    economic_outlook: str = Field(
        default="stable",
        description="经济展望: improving / stable / deteriorating",
    )
    summary: str = Field(default="", max_length=200, description="宏观面一句话总结")
