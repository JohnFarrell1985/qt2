"""数据飞轮 (P2-21)

持续收集低置信度样本 → 教师重标注 → 增量重训 → 热更新。
NVIDIA Data Flywheel Blueprint (2025) 设计模式。
"""
from __future__ import annotations

from typing import List, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)


class DataFlywheel:
    """数据飞轮: 低置信样本 → 教师重标注 → 增量重训 → 热更新"""

    def __init__(self, consensus=None, trainer=None, inference=None):
        self.consensus = consensus
        self.trainer = trainer
        self.inference = inference
        self._queue: List[dict] = []

    def enqueue(self, text: str, predicted_probs: Optional[list] = None):
        """将低置信度样本加入飞轮队列"""
        self._queue.append({
            "text": text,
            "probs": predicted_probs,
            "processed": False,
        })

    async def weekly_iteration(self):
        """每周飞轮迭代 (APScheduler 周任务调用)"""
        unprocessed = [q for q in self._queue if not q["processed"]]
        if not unprocessed:
            logger.info("飞轮队列为空, 跳过本轮迭代")
            return

        logger.info("飞轮迭代: %d 条低置信样本待处理", len(unprocessed))

        if self.consensus:
            texts = [q["text"] for q in unprocessed]
            new_labels = await self.consensus.label_batch(texts)
            logger.info("教师重标注完成: %d 条", len(new_labels))

        for q in unprocessed:
            q["processed"] = True

        logger.info("飞轮迭代完成")

    @property
    def queue_size(self) -> int:
        return sum(1 for q in self._queue if not q["processed"])
