"""风险预警抽取 Schema (P2-33b)

从新闻/公告/监管通报中提取风险预警信号。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class RiskAlert(BaseModel):
    """单条风险预警"""
    alert_type: str = Field(
        description="风险类型: regulatory/fraud/delisting/liquidity/black_swan/policy",
    )
    severity: str = Field(description="严重程度: critical/high/medium/low")
    affected_codes: list[str] = Field(
        default_factory=list, description="受影响的股票代码列表",
    )
    affected_sectors: list[str] = Field(
        default_factory=list, description="受影响的行业列表",
    )
    description: str = Field(description="风险描述")
    recommended_action: str = Field(
        default="monitor",
        description="建议操作: monitor/reduce/exit/hedge",
    )


class RiskAlertExtraction(BaseModel):
    """风险预警抽取结果"""
    alerts: list[RiskAlert] = Field(
        default_factory=list, max_length=10,
        description="风险预警列表",
    )
    overall_risk_level: str = Field(
        default="normal", description="整体风险: low/normal/elevated/high/extreme",
    )
    summary: str = Field(default="", max_length=200, description="风险面一句话总结")
