"""数据采集基类和数据结构定义

CollectResult: 采集结果统一封装
CollectTask: 采集任务描述
BaseCollector: 所有 Collector 的抽象基类
"""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.datacollect.rate_limiter import TokenBucketLimiter


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
        params: 采集参数字典 (函数名、过滤条件等)
    """
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    source: str = ""
    params: dict[str, Any] = field(default_factory=dict)


class BaseCollector(ABC):
    """数据采集器抽象基类。

    子类需实现 collect() 和 health_check() 方法。
    所有 Collector 共享限流器以控制对外部 API 的请求频率。
    """

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
