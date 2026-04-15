"""AI 新闻情报深度解读 Agent (P2-29)

多维度结构化输出: 事件类型、影响范围、时间窗口、置信度。
FinBERT2 快速过滤 + LLM 深度分析的两阶段管线。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)


class NewsIntelligenceAgent:
    """AI 新闻情报深度解读 — 多维度结构化输出"""

    OUTPUT_SCHEMA = {
        "event_type": "policy/earnings/merger/lawsuit/macro/rumor",
        "impact_scope": "stock/sector/market",
        "affected_codes": [],
        "affected_sectors": [],
        "sentiment_score": 0.0,
        "impact_magnitude": "low/medium/high/extreme",
        "time_horizon": "intraday/short/medium/long",
        "confidence": 0.0,
        "reasoning": "",
    }

    def __init__(self, llm_client=None, finbert_model=None):
        self.llm = llm_client
        self.finbert = finbert_model

    def analyze(self, news_items: List[Dict]) -> List[Dict]:
        """分析新闻列表, 返回结构化情报

        Args:
            news_items: [{"title": ..., "content": ..., "source": ...}]

        Returns:
            结构化情报列表
        """
        filtered = self._pre_filter(news_items)
        results = []

        for item in filtered:
            result = self._deep_analyze(item)
            if result:
                results.append(result)

        logger.info(
            "NewsIntelligence: %d 条新闻 → %d 条过滤 → %d 条情报",
            len(news_items), len(filtered), len(results),
        )
        return results

    def _pre_filter(self, items: List[Dict], threshold: float = 0.3) -> List[Dict]:
        """FinBERT2 快速过滤: 中性新闻直接跳过"""
        if self.finbert is None:
            return items

        filtered = []
        for item in items:
            text = item.get("title", "") + " " + item.get("content", "")[:200]
            try:
                result = self.finbert.predict(text)
                if result.get("label") != "neutral" or result.get("confidence", 0) < threshold:
                    filtered.append(item)
            except Exception:
                filtered.append(item)
        return filtered

    def _deep_analyze(self, item: Dict) -> Optional[Dict]:
        """LLM 深度分析"""
        text = item.get("title", "") + "\n" + item.get("content", "")
        if not text.strip():
            return None

        if self.llm:
            try:
                prompt = self._build_prompt(text)
                return self.llm.extract(prompt, schema=dict)
            except Exception as e:
                logger.debug("LLM 分析失败: %s", e)

        return self._rule_analyze(item)

    def _build_prompt(self, text: str) -> str:
        return f"""分析以下金融新闻, 输出结构化情报 JSON:

{text[:2000]}

输出字段:
- event_type: policy/earnings/merger/lawsuit/macro/rumor
- impact_scope: stock/sector/market
- affected_codes: 受影响股票代码列表
- affected_sectors: 受影响行业列表
- sentiment_score: -1 ~ +1
- impact_magnitude: low/medium/high/extreme
- time_horizon: intraday/short(1-5d)/medium(1-3m)/long(3m+)
- confidence: 0 ~ 1
- reasoning: 推理过程
"""

    @staticmethod
    def _rule_analyze(item: Dict) -> Dict:
        """规则降级"""
        title = item.get("title", "")
        positive_kw = ["利好", "上涨", "增持", "突破", "新高"]
        negative_kw = ["利空", "下跌", "减持", "暴跌", "跌停"]
        pos = sum(1 for kw in positive_kw if kw in title)
        neg = sum(1 for kw in negative_kw if kw in title)
        score = 0.3 if pos > neg else (-0.3 if neg > pos else 0.0)
        return {
            "event_type": "news",
            "impact_scope": "market",
            "affected_codes": [],
            "affected_sectors": [],
            "sentiment_score": score,
            "impact_magnitude": "medium",
            "time_horizon": "short",
            "confidence": 0.3,
            "reasoning": "规则分析",
        }
