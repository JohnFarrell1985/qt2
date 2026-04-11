"""规则清洗器 — 纯关键词/正则, LLM 全部失败时的最后防线

精度一般但免费, 标记 is_fallback=True 供下游区分质量。
"""

from __future__ import annotations

import re
from typing import Any

from src.dataclean.base import BaseCleaner, CleanResult

POSITIVE_KEYWORDS: list[str] = [
    "涨停", "利好", "上涨", "突破", "降准", "放量", "大涨", "暴涨", "利多", "买入",
]
NEGATIVE_KEYWORDS: list[str] = [
    "跌停", "利空", "下跌", "暴跌", "加息", "制裁", "大跌", "利淡", "卖出", "减持",
]
STOCK_CODE_PATTERN: re.Pattern[str] = re.compile(r"[036]\d{5}\.[A-Z]{2}")


class RuleCleaner(BaseCleaner):
    """纯规则清洗 — 关键词情绪 + 股票代码正则"""

    def get_schema(self) -> None:
        return None

    def clean(self, raw_data: Any) -> CleanResult:
        text = str(raw_data)

        pos = sum(1 for kw in POSITIVE_KEYWORDS if kw in text)
        neg = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text)
        total = pos + neg
        score = round((pos - neg) / max(total, 1), 2)

        codes = STOCK_CODE_PATTERN.findall(text)

        return CleanResult(
            engine="rule_fallback",
            schema_name="partial",
            cleaned_data={
                "news_sentiment_score": score,
                "hot_stocks": [
                    {"code": c, "reason": "关键词匹配", "sentiment": score}
                    for c in codes[:5]
                ],
                "market_mood_text": "规则提取(LLM不可用)",
            },
            raw_input=text[:500],
            llm_usage={},
            is_fallback=True,
        )
