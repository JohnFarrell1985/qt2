"""异步令牌桶限流器 — asyncio 兼容, 支持每域隔离

基于 asyncio event loop 时钟的令牌桶算法, 用于在异步上下文中控制外部数据源的请求频率。
与 TokenBucketLimiter 算法一致, 但使用 asyncio.Lock / asyncio.sleep 替代 threading 原语。
"""
from __future__ import annotations

import asyncio
import random

from src.common.logger import get_logger

logger = get_logger(__name__)


class AsyncTokenBucketLimiter:
    """异步令牌桶限流器, 不阻塞事件循环。

    Args:
        rate: 每秒填充的令牌数 (tokens/sec)
        burst: 桶的最大容量 (突发上限)
        jitter_pct: 等待时间的随机抖动比例, 用于防止 thundering-herd
    """

    _domain_limiters: dict[str, AsyncTokenBucketLimiter] = {}
    _domain_lock: asyncio.Lock | None = None

    def __init__(self, rate: float, burst: int, jitter_pct: float = 0.2):
        if rate <= 0:
            raise ValueError("rate must be positive")
        if burst <= 0:
            raise ValueError("burst must be positive")

        self._rate = rate
        self._burst = burst
        self._jitter_pct = max(0.0, min(jitter_pct, 1.0))

        self._tokens = float(burst)
        self._last_refill: float = 0.0
        self._lock = asyncio.Lock()

    @classmethod
    async def for_domain(
        cls, domain: str, rate: float, burst: int, **kwargs: float
    ) -> AsyncTokenBucketLimiter:
        """获取或创建指定域名的异步限流器实例 (单例模式)。"""
        if cls._domain_lock is None:
            cls._domain_lock = asyncio.Lock()
        async with cls._domain_lock:
            if domain not in cls._domain_limiters:
                cls._domain_limiters[domain] = cls(rate, burst, **kwargs)
                logger.debug(
                    "为域 %s 创建异步限流器 (rate=%.2f, burst=%d)",
                    domain, rate, burst,
                )
            return cls._domain_limiters[domain]

    @classmethod
    def reset_all(cls) -> None:
        """清空所有域限流器 (测试用)。"""
        cls._domain_limiters.clear()
        cls._domain_lock = None

    def _refill(self, now: float) -> None:
        """根据流逝时间补充令牌 (调用方需持有 _lock)。"""
        if self._last_refill == 0.0:
            self._last_refill = now
            return
        elapsed = now - self._last_refill
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
        self._last_refill = now

    def _wait_seconds(self) -> float:
        """计算获取一个令牌需要等待的秒数 (调用方需持有 _lock)。"""
        if self._tokens >= 1.0:
            return 0.0
        deficit = 1.0 - self._tokens
        base_wait = deficit / self._rate
        if self._jitter_pct > 0:
            jitter = base_wait * self._jitter_pct * random.random()
            base_wait += jitter
        return base_wait

    async def acquire(self, timeout: float | None = None) -> bool:
        """异步等待直到获取一个令牌。

        Args:
            timeout: 最大等待秒数, None 表示无限等待

        Returns:
            True 如果成功获取令牌, False 如果超时
        """
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout

        while True:
            async with self._lock:
                now = loop.time()
                self._refill(now)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                wait = self._wait_seconds()

            if deadline is not None:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    return False
                wait = min(wait, remaining)

            await asyncio.sleep(wait)

    async def try_acquire(self) -> bool:
        """非阻塞尝试获取一个令牌。"""
        async with self._lock:
            now = asyncio.get_running_loop().time()
            self._refill(now)
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    @property
    def rate(self) -> float:
        return self._rate

    @property
    def burst(self) -> int:
        return self._burst
