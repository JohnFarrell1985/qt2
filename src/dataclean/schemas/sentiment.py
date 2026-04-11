"""情绪引擎输出 Schema — SentimentExtraction

instructor 将此 Schema 自动注入 LLM 请求, Pydantic 校验失败时自动重试。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class KeyEvent(BaseModel):
    """单条重要事件"""

    event: str = Field(description="事件描述")
    impact: str = Field(description="positive/negative/neutral")
    magnitude: str = Field(description="high/medium/low")


class HotStock(BaseModel):
    """被频繁讨论的个股"""

    code: str = Field(description="股票代码, QMT格式如000001.SZ")
    reason: str = Field(description="被关注的原因")
    sentiment: float = Field(ge=-1, le=1, description="情绪评分 -1~+1")


class SentimentExtraction(BaseModel):
    """市场情绪结构化抽取结果"""

    news_sentiment_score: float = Field(ge=-1, le=1, description="整体新闻情绪 -1.0(极度悲观)到+1.0(极度乐观)")
    hot_sectors: list[str] = Field(default_factory=list, max_length=5, description="被提及最多的行业板块, 最多5个")
    key_events: list[KeyEvent] = Field(default_factory=list, max_length=10, description="重要事件列表")
    hot_stocks: list[HotStock] = Field(default_factory=list, max_length=10, description="被频繁讨论的个股")
    gold_price_usd: float | None = Field(default=None, description="黄金价格(美元)")
    crude_oil_usd: float | None = Field(default=None, description="原油价格(美元)")
    fx_usdcny: float | None = Field(default=None, description="美元兑人民币汇率")
    market_mood_text: str = Field(max_length=100, description="一句话市场总结, 最多100字")

    @field_validator("gold_price_usd", "crude_oil_usd", "fx_usdcny", mode="before")
    @classmethod
    def _empty_str_to_none(cls, v: object) -> object:
        """LLM 有时返回空字符串 "" 代替 null, 统一转为 None"""
        if v == "" or v == "null":
            return None
        return v
