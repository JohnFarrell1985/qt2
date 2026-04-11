"""代理 IP 轮换管理器 — Round-Robin 池 + Per-IP 限流 + 自动拉黑

Features:
- Round-robin / Random 轮换策略
- Per-IP + Per-Domain 令牌桶限流
- 被封 IP 自动拉黑, 冷却后恢复
- 池空时优雅降级为直连
"""
from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

from src.common.config import settings
from src.common.logger import get_logger
from src.datacollect.async_rate_limiter import AsyncTokenBucketLimiter

logger = get_logger(__name__)


class RotateStrategy(Enum):
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"


@dataclass
class ProxyConfig:
    """代理配置。

    Attributes:
        url: 完整代理 URL (如 http://user:pass@1.2.3.4:8080)
        ip: 代理 IP (自动从 URL 解析)
    """

    url: str
    ip: str = ""

    def __post_init__(self) -> None:
        if not self.ip:
            parsed = urlparse(self.url)
            self.ip = parsed.hostname or self.url

    def as_dict(self) -> dict[str, str]:
        return {"http": self.url, "https": self.url}


class AllProxiesBlacklisted(Exception):
    """所有代理均被拉黑时抛出。"""


class ProxyPoolManager:
    """代理 IP 轮换管理器。

    Features:
    - Round-robin rotation across proxies
    - Per-IP rate limiting via AsyncTokenBucketLimiter
    - Auto-blacklisting of blocked proxies with configurable cooldown
    - Graceful degradation to direct connection when no proxies available
    """

    def __init__(
        self,
        proxies: list[ProxyConfig] | None = None,
        default_rate: float = 0.15,
        default_burst: int = 1,
        blacklist_cooldown_sec: float = 600.0,
        strategy: RotateStrategy = RotateStrategy.ROUND_ROBIN,
    ):
        self._pool: deque[ProxyConfig] = deque(proxies or [])
        self._default_rate = default_rate
        self._default_burst = default_burst
        self._blacklist_cooldown_sec = blacklist_cooldown_sec
        self._strategy = strategy
        self._per_ip_limiters: dict[str, AsyncTokenBucketLimiter] = {}
        self._blacklist: set[str] = set()
        self._lock = asyncio.Lock()
        self._enabled = len(self._pool) > 0

    @classmethod
    def from_env(cls) -> ProxyPoolManager:
        """从环境变量 / 配置创建代理池。"""
        cfg = settings.datacollect
        proxy_urls_str = cfg.proxy_urls or ""
        if not proxy_urls_str:
            return cls(proxies=[])

        urls = [u.strip() for u in proxy_urls_str.split(",") if u.strip()]
        proxies = [ProxyConfig(url=u) for u in urls]

        strategy_str = cfg.proxy_rotate_strategy
        strategy = (
            RotateStrategy.RANDOM
            if strategy_str == "random"
            else RotateStrategy.ROUND_ROBIN
        )
        return cls(
            proxies=proxies,
            blacklist_cooldown_sec=float(cfg.proxy_blacklist_cooldown),
            strategy=strategy,
        )

    @property
    def enabled(self) -> bool:
        return self._enabled and len(self._pool) > 0

    @property
    def pool_size(self) -> int:
        return len(self._pool)

    @property
    def blacklisted_count(self) -> int:
        return len(self._blacklist)

    @property
    def available_count(self) -> int:
        return sum(1 for p in self._pool if p.ip not in self._blacklist)

    async def acquire(self, domain: str) -> ProxyConfig | None:
        """获取下一个可用代理 (含 per-IP 限流)。

        Returns:
            ProxyConfig 或 None (池空/未启用时返回 None, 调用方应直连)。

        Raises:
            AllProxiesBlacklisted: 所有代理均被拉黑。
        """
        if not self._enabled:
            return None

        limiter: AsyncTokenBucketLimiter | None = None
        proxy: ProxyConfig | None = None

        async with self._lock:
            for _ in range(len(self._pool)):
                if self._strategy == RotateStrategy.ROUND_ROBIN:
                    candidate = self._pool[0]
                    self._pool.rotate(-1)
                else:
                    import random

                    idx = random.randint(0, len(self._pool) - 1)
                    candidate = self._pool[idx]

                if candidate.ip not in self._blacklist:
                    limiter_key = f"{candidate.ip}:{domain}"
                    if limiter_key not in self._per_ip_limiters:
                        self._per_ip_limiters[limiter_key] = (
                            AsyncTokenBucketLimiter(
                                rate=self._default_rate,
                                burst=self._default_burst,
                            )
                        )
                    limiter = self._per_ip_limiters[limiter_key]
                    proxy = candidate
                    break
            else:
                raise AllProxiesBlacklisted(
                    f"All {len(self._pool)} proxies are blacklisted",
                )

        await limiter.acquire()  # type: ignore[union-attr]
        return proxy

    async def report_blocked(self, proxy: ProxyConfig) -> None:
        """标记代理被封, 冷却后自动恢复。"""
        async with self._lock:
            self._blacklist.add(proxy.ip)
        logger.warning(
            "proxy %s blacklisted for %.0fs",
            proxy.ip,
            self._blacklist_cooldown_sec,
        )

        async def _unblock() -> None:
            await asyncio.sleep(self._blacklist_cooldown_sec)
            async with self._lock:
                self._blacklist.discard(proxy.ip)
            logger.info("proxy %s recovered from blacklist", proxy.ip)

        asyncio.create_task(_unblock())

    async def report_success(self, proxy: ProxyConfig) -> None:
        """记录代理成功请求 (预留扩展)。"""

    def add_proxy(self, proxy: ProxyConfig) -> None:
        """动态添加代理到池中。"""
        self._pool.append(proxy)
        self._enabled = True
        logger.info(
            "proxy added: %s (pool size: %d)", proxy.ip, len(self._pool),
        )

    def remove_proxy(self, proxy_ip: str) -> None:
        """从池中移除代理。"""
        self._pool = deque(p for p in self._pool if p.ip != proxy_ip)
        self._blacklist.discard(proxy_ip)
        self._enabled = len(self._pool) > 0

    def get_stats(self) -> dict[str, object]:
        """获取代理池统计信息。"""
        return {
            "enabled": self._enabled,
            "total": len(self._pool),
            "available": self.available_count,
            "blacklisted": self.blacklisted_count,
            "strategy": self._strategy.value,
        }
