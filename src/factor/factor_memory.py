"""因子经验记忆 — Embedding 检索去重 (P2-24)

维护因子经验记忆库 (已拒绝/已上线因子的 embedding),
LLM 生成新因子前先检索去重, 避免反复挖掘同类因子。

参考: FactorMiner (arXiv:2602.14670)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FactorRecord:
    """因子记录"""
    name: str
    description: str
    embedding: Optional[np.ndarray] = None
    status: str = "candidate"
    metrics: Dict[str, float] = field(default_factory=dict)


class FactorMemory:
    """因子经验记忆: embedding 检索去重"""

    def __init__(self, embedding_dim: int = 768, similarity_threshold: float = 0.85):
        self.records: List[FactorRecord] = []
        self.embedding_dim = embedding_dim
        self.threshold = similarity_threshold

    def is_duplicate(self, description: str) -> bool:
        """检查新因子是否与已有因子重复"""
        new_emb = self._embed(description)
        for rec in self.records:
            if rec.embedding is not None:
                sim = self._cosine_similarity(new_emb, rec.embedding)
                if sim > self.threshold:
                    logger.debug(
                        "因子重复 (%.3f > %.3f): '%s' ≈ '%s'",
                        sim, self.threshold, description[:50], rec.description[:50],
                    )
                    return True
        return False

    def record(
        self,
        name: str,
        description: str,
        status: str = "candidate",
        metrics: Optional[Dict[str, float]] = None,
    ) -> None:
        """记录因子"""
        emb = self._embed(description)
        self.records.append(FactorRecord(
            name=name,
            description=description,
            embedding=emb,
            status=status,
            metrics=metrics or {},
        ))

    def search_similar(self, description: str, top_k: int = 5) -> List[Tuple[str, float]]:
        """检索最相似的已有因子"""
        new_emb = self._embed(description)
        similarities = []
        for rec in self.records:
            if rec.embedding is not None:
                sim = self._cosine_similarity(new_emb, rec.embedding)
                similarities.append((rec.name, sim))
        return sorted(similarities, key=lambda x: x[1], reverse=True)[:top_k]

    def get_successful_patterns(self, top_k: int = 10) -> List[FactorRecord]:
        """获取成功的因子模式 (供 LLM 参考)"""
        successful = [r for r in self.records if r.status == "accepted"]
        return sorted(successful, key=lambda r: r.metrics.get("ic", 0), reverse=True)[:top_k]

    def _embed(self, text: str) -> np.ndarray:
        """文本 → embedding (简化: 使用随机 hash, 生产用 text-embedding-3-small)"""
        rng = np.random.default_rng(hash(text) % (2**31))
        emb = rng.standard_normal(self.embedding_dim)
        return emb / np.linalg.norm(emb)

    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        dot = np.dot(a, b)
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return float(dot / (norm_a * norm_b))
