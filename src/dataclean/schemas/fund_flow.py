"""资金流向抽取 Schema (P2-11)

从财经新闻/数据中提取资金流向信号: 北向资金、融资融券、主力大单。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class FundFlowSignal(BaseModel):
    """单条资金流向信号"""
    flow_type: str = Field(description="northbound(北向) / margin(融资) / block(大单)")
    direction: str = Field(description="inflow(流入) / outflow(流出)")
    amount_billion: float | None = Field(default=None, description="金额(亿元)")
    target: str = Field(default="market", description="影响范围: market/sector/stock")
    target_name: str = Field(default="", description="具体标的名称")
    significance: str = Field(default="normal", description="normal/significant/extreme")


class FundFlowExtraction(BaseModel):
    """资金流向抽取结果"""
    signals: list[FundFlowSignal] = Field(
        default_factory=list, max_length=20,
        description="资金流向信号列表",
    )
    north_net_flow_billion: float | None = Field(
        default=None, description="北向资金净流入(亿元)",
    )
    margin_balance_change: float | None = Field(
        default=None, description="融资余额变化(亿元)",
    )
    summary: str = Field(default="", max_length=200, description="资金面一句话总结")
