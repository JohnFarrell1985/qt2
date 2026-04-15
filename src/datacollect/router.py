"""CollectRouter — 自适应数据采集路由 (P2-32a)

降级链: akshare (免费) → HTTP 爬虫 → Playwright 浏览器 → Tavily API (付费兜底)。
与 FallbackDispatcher 的区别: Router 管理数据源级别的健康状态和自动降级,
Dispatcher 管理同一数据类型在多数据源间的降级。
"""
from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional

from src.common.config import settings
from src.common.logger import get_logger
from src.datacollect.base import CollectResult

logger = get_logger(__name__)


class SourceHealth:
    """数据源健康状态追踪"""

    __slots__ = ("name", "success_count", "fail_count", "last_fail_ts", "consecutive_fails")

    def __init__(self, name: str):
        self.name = name
        self.success_count = 0
        self.fail_count = 0
        self.last_fail_ts = 0.0
        self.consecutive_fails = 0

    @property
    def is_healthy(self) -> bool:
        cooldown = settings.datacollect.circuit_breaker_cooldown
        if self.consecutive_fails >= settings.datacollect.circuit_breaker_threshold:
            if time.time() - self.last_fail_ts < cooldown:
                return False
            self.consecutive_fails = 0
        return True

    def record_success(self):
        self.success_count += 1
        self.consecutive_fails = 0

    def record_failure(self):
        self.fail_count += 1
        self.consecutive_fails += 1
        self.last_fail_ts = time.time()


class CollectRouter:
    """自适应采集路由 — 按健康状态自动选择数据源

    内置降级链 (可通过 register 扩展):
    1. akshare (免费, 限流)
    2. http_collector (通用爬虫)
    3. browser_collector (Playwright 反爬)
    4. tavily_collector (付费 API 兜底)
    """

    def __init__(self):
        self._sources: Dict[str, Callable[..., CollectResult]] = {}
        self._chain: List[str] = []
        self._health: Dict[str, SourceHealth] = {}

    def register(self, name: str, handler: Callable[..., CollectResult], priority: int = 100):
        """注册数据源

        Args:
            name: 数据源名称
            handler: 采集函数, 接受 (**kwargs) 返回 CollectResult
            priority: 优先级 (越小越优先)
        """
        self._sources[name] = handler
        self._health[name] = SourceHealth(name)
        self._chain.append(name)
        self._chain.sort(key=lambda n: priority)

    def route(self, **kwargs: Any) -> Optional[CollectResult]:
        """按降级链路由采集请求

        依次尝试健康的数据源, 成功即返回。全部失败返回 None。
        """
        for name in self._chain:
            health = self._health.get(name)
            if health and not health.is_healthy:
                logger.debug("数据源 %s 熔断中, 跳过", name)
                continue

            handler = self._sources.get(name)
            if handler is None:
                continue

            try:
                result = handler(**kwargs)
                if result and result.success:
                    if health:
                        health.record_success()
                    logger.debug("路由成功: %s", name)
                    return result
            except Exception as e:
                logger.warning("数据源 %s 异常: %s", name, e)
                if health:
                    health.record_failure()

        logger.error("所有数据源均失败")
        return None

    def get_health_report(self) -> List[dict]:
        return [
            {
                "name": h.name,
                "healthy": h.is_healthy,
                "success": h.success_count,
                "fail": h.fail_count,
                "consecutive_fails": h.consecutive_fails,
            }
            for h in self._health.values()
        ]
