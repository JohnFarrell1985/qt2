"""多教师共识标注管线 (P2-19)

双教师独立标注 + 分歧仲裁 (EvasionBench 2026 方法):
- 两个 LLM 独立对同一文本分类
- 一致 → 高置信标签
- 分歧 → Judge 模型仲裁, 标记为 hard example

参考: EvasionBench (arXiv:2601.09142), ODA-Fin (arXiv:2603.07223)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ConsensusLabel:
    """共识标注结果"""
    text: str
    label: str
    confidence: float = 1.0
    is_hard: bool = False
    teacher_agreement: bool = True
    teacher_a_label: str = ""
    teacher_b_label: str = ""
    difficulty_score: float = 0.0
    metadata: dict = field(default_factory=dict)


class ConsensusArbiter:
    """双教师共识仲裁 + 难度评分"""

    def __init__(self, llm_client=None, judge_model: str = "deepseek-r1"):
        self.llm = llm_client
        self.judge_model = judge_model

    async def label_batch(self, texts: List[str]) -> List[ConsensusLabel]:
        """批量双教师标注

        Args:
            texts: 待标注文本列表

        Returns:
            ConsensusLabel 列表
        """
        if self.llm is None:
            logger.warning("LLM 客户端不可用, 使用规则降级")
            return [self._rule_fallback(t) for t in texts]

        results = []
        for text in texts:
            try:
                label_a = await self._classify(text, model="deepseek")
                label_b = await self._classify(text, model="qwen")

                if label_a == label_b:
                    results.append(ConsensusLabel(
                        text=text, label=label_a,
                        confidence=1.0, is_hard=False,
                        teacher_agreement=True,
                        teacher_a_label=label_a,
                        teacher_b_label=label_b,
                    ))
                else:
                    judge_label = await self._classify(
                        text, model=self.judge_model,
                        context=f"教师A: {label_a}, 教师B: {label_b}",
                    )
                    results.append(ConsensusLabel(
                        text=text, label=judge_label,
                        confidence=0.6, is_hard=True,
                        teacher_agreement=False,
                        teacher_a_label=label_a,
                        teacher_b_label=label_b,
                    ))
            except Exception as e:
                logger.warning("标注失败, 回退规则: %s", e)
                results.append(self._rule_fallback(text))

        return results

    async def _classify(self, text: str, model: str, context: str = "") -> str:
        """调用 LLM 分类"""
        prompt = f"将以下金融文本分类为 positive/negative/neutral:\n{text[:500]}"
        if context:
            prompt += f"\n参考: {context}"
        resp = await self.llm.aclassify(prompt, model=model)
        return resp

    @staticmethod
    def _rule_fallback(text: str) -> ConsensusLabel:
        """规则降级: 关键词匹配"""
        positive_kw = ["利好", "上涨", "突破", "增持", "买入", "新高"]
        negative_kw = ["利空", "下跌", "跌停", "减持", "卖出", "暴跌"]
        pos = sum(1 for kw in positive_kw if kw in text)
        neg = sum(1 for kw in negative_kw if kw in text)
        if pos > neg:
            label = "positive"
        elif neg > pos:
            label = "negative"
        else:
            label = "neutral"
        return ConsensusLabel(
            text=text, label=label,
            confidence=0.3, is_hard=False,
            teacher_agreement=True,
        )

    def score_difficulty(
        self, labels: List[ConsensusLabel], base_student=None,
    ) -> tuple[List[ConsensusLabel], List[ConsensusLabel]]:
        """ODA-Fin 风格难度评分

        Args:
            labels: 共识标注结果
            base_student: 未训练的学生模型 (可选)

        Returns:
            (easy_set, hard_set)
        """
        if base_student is None:
            easy = [l for l in labels if not l.is_hard]
            hard = [l for l in labels if l.is_hard]
            return easy, hard

        for label in labels:
            pred = base_student.predict(label.text)
            label.difficulty_score = 1.0 if pred != label.label else 0.0

        easy = [l for l in labels if l.difficulty_score == 0]
        hard = [l for l in labels if l.difficulty_score > 0]
        return easy, hard
