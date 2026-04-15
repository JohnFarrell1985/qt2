"""RAG 投研知识库 (P2-25)

清洗后文档 → embedding → 向量检索 → LLM 生成回答。
基础设施层, 供 P2-26 双塔检索和 P2-30 论文阅读复用。

参考: CARAG (EACL 2026), LLM-RAG 金融分析 (arXiv:2504.06279)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Chunk:
    """文档块"""
    text: str
    source: str = ""
    score: float = 0.0
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class SimpleVectorStore:
    """简化向量存储 (生产版建议替换为 Chroma/Milvus)"""

    def __init__(self):
        self._chunks: List[Chunk] = []
        self._embeddings: list = []

    def add(self, text: str, source: str = "", metadata: Optional[dict] = None):
        self._chunks.append(Chunk(text=text, source=source, metadata=metadata or {}))

    def search(self, query: str, top_k: int = 5) -> List[Chunk]:
        """文本相似度搜索 (简化实现: 关键词匹配)"""
        scored = []
        query_words = set(query.lower().split())
        for chunk in self._chunks:
            chunk_words = set(chunk.text.lower().split())
            overlap = len(query_words & chunk_words)
            scored.append((chunk, overlap))
        scored.sort(key=lambda x: x[1], reverse=True)
        return [Chunk(text=c.text, source=c.source, score=s, metadata=c.metadata)
                for c, s in scored[:top_k] if s > 0]

    @property
    def size(self) -> int:
        return len(self._chunks)


class ResearchRAG:
    """RAG 投研知识库"""

    def __init__(self, llm_client=None):
        self.vector_store = SimpleVectorStore()
        self.llm = llm_client

    def ingest(self, text: str, source: str = "", chunk_size: int = 500):
        """摄入文档 (自动分块)"""
        for i in range(0, len(text), chunk_size):
            chunk = text[i: i + chunk_size]
            self.vector_store.add(chunk, source=source)
        logger.info("已摄入文档: %s (%d 块)", source, len(text) // chunk_size + 1)

    def query(self, question: str, top_k: int = 5) -> str:
        """RAG 查询: 检索 → LLM 生成"""
        chunks = self.vector_store.search(question, top_k=top_k)
        if not chunks:
            return "未找到相关文档。"

        context = "\n\n".join([f"[{c.source}] {c.text}" for c in chunks])

        if self.llm:
            try:
                return self.llm.generate(
                    f"基于以下研报/公告内容回答问题:\n{context}\n\n问题: {question}"
                )
            except Exception as e:
                logger.warning("LLM 生成失败: %s", e)

        return f"相关内容 ({len(chunks)} 块):\n{context}"
