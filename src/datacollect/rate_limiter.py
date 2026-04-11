"""令牌桶限流器 — 线程安全, 支持每域隔离

基于 time.monotonic 的经典令牌桶算法, 用于控制外部数据源的请求频率。
"""
import random
import threading
import time

from src.common.logger import get_logger

logger = get_logger(__name__)


class TokenBucketLimiter:
    """线程安全的令牌桶限流器。

    Args:
        rate: 每秒填充的令牌数 (tokens/sec)
        burst: 桶的最大容量 (突发上限)
        jitter_pct: 等待时间的随机抖动比例, 用于防止 thundering-herd
    """

    _domain_limiters: dict[str, "TokenBucketLimiter"] = {}
    _domain_lock = threading.Lock()

    def __init__(self, rate: float, burst: int, jitter_pct: float = 0.2):
        if rate <= 0:
            raise ValueError("rate must be positive")
        if burst <= 0:
            raise ValueError("burst must be positive")

        self._rate = rate
        self._burst = burst
        self._jitter_pct = max(0.0, min(jitter_pct, 1.0))

        self._tokens = float(burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    @classmethod
    def for_domain(cls, domain: str, rate: float, burst: int, **kwargs) -> "TokenBucketLimiter":
        """获取或创建指定域名的限流器实例 (单例模式)。"""
        with cls._domain_lock:
            if domain not in cls._domain_limiters:
                cls._domain_limiters[domain] = cls(rate, burst, **kwargs)
                logger.debug("为域 %s 创建限流器 (rate=%.2f, burst=%d)", domain, rate, burst)
            return cls._domain_limiters[domain]

    @classmethod
    def reset_all(cls) -> None:
        """清空所有域限流器 (测试用)。"""
        with cls._domain_lock:
            cls._domain_limiters.clear()

    def _refill(self) -> None:
        """根据流逝时间补充令牌 (调用方需持有 _lock)。"""
        now = time.monotonic()
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

    def acquire(self, timeout: float | None = None) -> bool:
        """阻塞直到获取一个令牌。

        Args:
            timeout: 最大等待秒数, None 表示无限等待

        Returns:
            True 如果成功获取令牌, False 如果超时
        """
        deadline = None if timeout is None else time.monotonic() + timeout

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                wait = self._wait_seconds()

            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                wait = min(wait, remaining)

            time.sleep(wait)

    def try_acquire(self) -> bool:
        """非阻塞尝试获取一个令牌。"""
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    @property
    def available_tokens(self) -> float:
        """当前可用令牌数 (近似值, 用于监控)。"""
        with self._lock:
            self._refill()
            return self._tokens
