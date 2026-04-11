"""数据采集基类和数据结构定义

CollectResult: 采集结果统一封装
CollectTask: 采集任务描述 (含幂等键)
StreamResult: 流式采集统计结果
BaseCollector: 所有 Collector 的抽象基类
"""
from __future__ import annotations

import hashlib
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.common.logger import get_logger
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)


@dataclass
class CollectResult:
    """采集结果统一封装。

    Attributes:
        source: 数据来源标识 (如 "akshare", "tushare")
        data: 采集到的数据, 通常为 pandas DataFrame
        collected_at: 采集完成时间
        metadata: 附加元信息 (函数名、参数、耗时等)
    """
    source: str
    data: Any
    collected_at: datetime = field(default_factory=datetime.now)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class CollectTask:
    """采集任务描述。

    Attributes:
        task_id: 唯一任务标识
        source: 数据来源标识
        data_type: 数据类型标识 (如 "stock_daily")
        params: 采集参数字典 (函数名、过滤条件等)
        idempotency_key: 幂等键, 自动根据 source + data_type + params 生成
    """
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    source: str = ""
    data_type: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str = ""

    def __post_init__(self) -> None:
        if not self.idempotency_key:
            raw = f"{self.source}:{self.data_type}:{sorted(self.params.items())}"
            self.idempotency_key = hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class StreamResult:
    """流式采集统计结果。

    Attributes:
        total: 任务总数
        success: 成功数
        failed: 失败数
    """
    total: int
    success: int
    failed: int


class BaseCollector(ABC):
    """数据采集器抽象基类。

    子类需实现 collect() 和 health_check() 方法。
    所有 Collector 共享限流器以控制对外部 API 的请求频率。
    """

    STREAM_BATCH_SIZE: int = 100

    def __init__(self, limiter: TokenBucketLimiter | None = None):
        self._limiter = limiter

    @property
    def limiter(self) -> TokenBucketLimiter | None:
        return self._limiter

    @abstractmethod
    def collect(self, task: CollectTask) -> CollectResult:
        """执行数据采集任务。

        Args:
            task: 采集任务描述

        Returns:
            采集结果
        """

    @abstractmethod
    def health_check(self) -> bool:
        """检查数据源是否可用。

        Returns:
            True 如果数据源正常可达
        """

    def collect_stream(
        self,
        tasks: list[CollectTask],
        persist_fn: Callable[[list[CollectResult]], None] | None = None,
        dead_letter_fn: Callable[[CollectTask, Exception], None] | None = None,
    ) -> StreamResult:
        """Stream-process tasks in batches with per-batch persistence.

        Args:
            tasks: list of CollectTask to process
            persist_fn: callback for batch persistence
            dead_letter_fn: callback for failed tasks
        """
        total, success, failed = len(tasks), 0, 0
        for i in range(0, len(tasks), self.STREAM_BATCH_SIZE):
            batch = tasks[i : i + self.STREAM_BATCH_SIZE]
            batch_results: list[CollectResult] = []
            for task in batch:
                try:
                    result = self.collect(task)
                    batch_results.append(result)
                    success += 1
                except Exception as exc:
                    failed += 1
                    if dead_letter_fn:
                        dead_letter_fn(task, exc)
                    logger.warning(
                        "collect_stream task %s failed: %s", task.task_id, exc,
                    )
            if batch_results and persist_fn:
                persist_fn(batch_results)
            logger.info(
                "stream_progress total=%d success=%d failed=%d",
                total, success, failed,
            )
        return StreamResult(total=total, success=success, failed=failed)
