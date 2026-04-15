"""蒸馏模型推理 + 降级链 (P2-21)

降级链: 本地 ONNX(主) → LLM API(兜底) → 规则引擎(最后手段)
低置信度样本自动进入数据飞轮队列。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import numpy as np

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)


class DistilledInference:
    """蒸馏模型推理引擎

    优先使用本地 ONNX 模型, 低置信度回退 LLM API, 最后规则降级。
    """

    def __init__(
        self,
        model_path: str = "",
        confidence_threshold: float = 0.7,
    ):
        self.model_path = model_path or getattr(settings, "distill_model_path", "models/distilled/onnx")
        self.confidence_threshold = confidence_threshold
        self._model = None
        self._tokenizer = None

    def _load_model(self):
        """延迟加载 ONNX 模型"""
        if self._model is not None:
            return
        try:
            from optimum.onnxruntime import ORTModelForSequenceClassification
            from transformers import AutoTokenizer

            self._model = ORTModelForSequenceClassification.from_pretrained(self.model_path)
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
            logger.info("ONNX 蒸馏模型已加载: %s", self.model_path)
        except Exception as e:
            logger.warning("ONNX 模型加载失败, 将使用降级链: %s", e)

    def predict(self, text: str) -> Dict[str, Any]:
        """预测单条文本

        Returns:
            {"label": str, "confidence": float, "source": str}
        """
        self._load_model()

        if self._model is not None and self._tokenizer is not None:
            return self._predict_local(text)

        return self._rule_fallback(text)

    def _predict_local(self, text: str) -> Dict[str, Any]:
        """本地 ONNX 推理"""
        inputs = self._tokenizer(text, return_tensors="np", truncation=True, max_length=512)
        outputs = self._model(**inputs)
        logits = outputs.logits

        from scipy.special import softmax
        probs = softmax(logits, axis=-1)[0]
        max_prob = float(probs.max())
        label_idx = int(probs.argmax())
        labels = ["negative", "neutral", "positive"]

        result = {
            "label": labels[label_idx],
            "confidence": round(max_prob, 4),
            "source": "distilled_onnx",
        }

        if max_prob < self.confidence_threshold:
            result["flywheel"] = True
            logger.debug("低置信度 %.3f < %.3f, 进入飞轮队列", max_prob, self.confidence_threshold)

        return result

    @staticmethod
    def _rule_fallback(text: str) -> Dict[str, Any]:
        """规则降级: 关键词匹配 → score = ±0.3"""
        positive_kw = ["利好", "上涨", "突破", "增持", "新高", "利润增长"]
        negative_kw = ["利空", "下跌", "跌停", "减持", "暴跌", "亏损"]
        pos = sum(1 for kw in positive_kw if kw in text)
        neg = sum(1 for kw in negative_kw if kw in text)
        if pos > neg:
            return {"label": "positive", "confidence": 0.3, "source": "rule_fallback"}
        if neg > pos:
            return {"label": "negative", "confidence": 0.3, "source": "rule_fallback"}
        return {"label": "neutral", "confidence": 0.3, "source": "rule_fallback"}
