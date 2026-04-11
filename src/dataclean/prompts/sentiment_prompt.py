"""情绪清洗 Prompt v2 — few-shot + auto-schema + 负约束

设计原则:
- 100% 静态 (无 datetime/uuid), 触发 DeepSeek Prefix Caching (降 90% 输入成本)
- Schema 由 model_json_schema() 自动生成, 确保 prompt 与 Pydantic 定义永远一致
- f-string 在 import 时求值, 进程生命周期内不可变
"""

from __future__ import annotations

import json

from src.dataclean.schemas.sentiment import SentimentExtraction

PROMPT_VERSION = "sentiment-v2"

_SCHEMA_JSON = json.dumps(SentimentExtraction.model_json_schema(), ensure_ascii=False, indent=2)

SENTIMENT_PROMPT = f"""你是A股市场数据分析师。将以下市场信息提取为标准JSON。

## 规则
1. news_sentiment_score: 整体新闻情绪 -1.0(极度悲观)到+1.0(极度乐观)
2. hot_sectors: 被提及最多的行业板块, 最多5个
3. key_events: 重要事件, 含 event(描述), impact(positive/negative/neutral), magnitude(high/medium/low)
4. hot_stocks: 被频繁讨论的个股, 含 code(QMT格式如000001.SZ), reason(原因), sentiment(-1~1)
5. market_mood_text: 一句话市场总结, 最多100字
6. 过滤广告、营销推广、不相关内容
7. 去重: 相同事件只保留一条

## 禁止
- 不要编造不存在的股票代码
- 不要包含广告或营销推广内容
- 不要在 hot_stocks 中包含未在原文中提及的股票
- 不要输出 JSON 以外的任何文本

## JSON Schema
{_SCHEMA_JSON}

## 示例

输入: "央行降准50bp, 银行股集体涨停, 北向资金净流入120亿, 贵州茅台跌2%受白酒板块拖累"

输出:
{{
  "news_sentiment_score": 0.5,
  "hot_sectors": ["银行", "券商", "白酒"],
  "key_events": [
    {{"event": "央行降准50bp", "impact": "positive", "magnitude": "high"}},
    {{"event": "北向资金净流入120亿", "impact": "positive", "magnitude": "medium"}},
    {{"event": "白酒板块整体下跌", "impact": "negative", "magnitude": "low"}}
  ],
  "hot_stocks": [
    {{"code": "600519.SH", "reason": "白酒板块拖累下跌2%", "sentiment": -0.3}}
  ],
  "gold_price_usd": null,
  "crude_oil_usd": null,
  "fx_usdcny": null,
  "market_mood_text": "央行降准提振银行股, 整体偏乐观但白酒板块承压"
}}"""
