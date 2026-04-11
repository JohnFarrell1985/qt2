"""数据源健康仪表盘 — 汇总各域的请求统计与健康评分

health_score 计算:
  success_rate × 60 + latency_bonus(最高 20) + circuit_bonus(CLOSED=20, HALF_OPEN=10, OPEN=0)
"""
from __future__ import annotations

import threading
from dataclasses import dataclass

from src.common.logger import get_logger

logger = get_logger(__name__)

_LATENCY_GOOD_MS = 500.0
_LATENCY_MAX_MS = 5000.0


@dataclass
class SourceHealthMetrics:
    """单个数据源的健康指标。"""
    domain: str
    total_requests: int = 0
    success_count: int = 0
    block_count: int = 0
    timeout_count: int = 0
    error_count: int = 0
    latency_sum: float = 0.0
    circuit_state: str = "closed"
    current_interval: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 1.0
        return self.success_count / self.total_requests

    @property
    def avg_latency_ms(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return (self.latency_sum / self.total_requests) * 1000.0

    @property
    def health_score(self) -> float:
        """综合健康评分 (0–100)。"""
        sr_component = self.success_rate * 60.0

        avg_ms = self.avg_latency_ms
        if avg_ms <= _LATENCY_GOOD_MS:
            lat_component = 20.0
        elif avg_ms >= _LATENCY_MAX_MS:
            lat_component = 0.0
        else:
            ratio = (avg_ms - _LATENCY_GOOD_MS) / (_LATENCY_MAX_MS - _LATENCY_GOOD_MS)
            lat_component = 20.0 * (1.0 - ratio)

        circuit_map = {"closed": 20.0, "half_open": 10.0, "open": 0.0}
        cir_component = circuit_map.get(self.circuit_state, 0.0)

        return min(100.0, sr_component + lat_component + cir_component)


class SourceHealthDashboard:
    """数据源健康仪表盘 (线程安全, 单例)。"""

    _instance: SourceHealthDashboard | None = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._metrics: dict[str, SourceHealthMetrics] = {}
        self._lock = threading.Lock()

    @classmethod
    def instance(cls) -> SourceHealthDashboard:
        """获取全局单例。"""
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
                logger.debug("创建 SourceHealthDashboard 单例")
            return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """销毁单例 (测试用)。"""
        with cls._instance_lock:
            cls._instance = None

    # ------------------------------------------------------------------
    # 记录
    # ------------------------------------------------------------------

    def record_request(
        self,
        domain: str,
        status_code: int,
        latency: float,
    ) -> None:
        """记录一次请求的结果。"""
        with self._lock:
            m = self._get_or_create(domain)
            m.total_requests += 1
            m.latency_sum += latency

            if 200 <= status_code < 400:
                m.success_count += 1
            elif status_code in (429, 403):
                m.block_count += 1
            elif status_code == 0:
                m.timeout_count += 1
            else:
                m.error_count += 1

    def update_circuit_state(self, domain: str, state: str) -> None:
        """更新域的熔断状态。"""
        with self._lock:
            m = self._get_or_create(domain)
            m.circuit_state = state

    def update_interval(self, domain: str, interval: float) -> None:
        """更新域当前请求间隔。"""
        with self._lock:
            m = self._get_or_create(domain)
            m.current_interval = interval

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    def get_health(self, domain: str) -> SourceHealthMetrics:
        """获取指定域的健康指标 (不存在则返回空指标)。"""
        with self._lock:
            m = self._metrics.get(domain)
            if m is None:
                return SourceHealthMetrics(domain=domain)
            return _clone_metrics(m)

    def get_all_health(self) -> dict[str, SourceHealthMetrics]:
        """获取所有域的健康指标。"""
        with self._lock:
            return {k: _clone_metrics(v) for k, v in self._metrics.items()}

    def get_ranked_sources(self) -> list[SourceHealthMetrics]:
        """按 health_score 降序排列的源列表。"""
        all_health = self.get_all_health()
        return sorted(
            all_health.values(),
            key=lambda m: m.health_score,
            reverse=True,
        )

    def reset(self, domain: str) -> None:
        """重置指定域的统计。"""
        with self._lock:
            if domain in self._metrics:
                del self._metrics[domain]
                logger.info("[%s] 健康指标已重置", domain)

    # ------------------------------------------------------------------
    # 内部 (调用方持有 _lock)
    # ------------------------------------------------------------------

    def _get_or_create(self, domain: str) -> SourceHealthMetrics:
        if domain not in self._metrics:
            self._metrics[domain] = SourceHealthMetrics(domain=domain)
        return self._metrics[domain]


def _clone_metrics(m: SourceHealthMetrics) -> SourceHealthMetrics:
    return SourceHealthMetrics(
        domain=m.domain,
        total_requests=m.total_requests,
        success_count=m.success_count,
        block_count=m.block_count,
        timeout_count=m.timeout_count,
        error_count=m.error_count,
        latency_sum=m.latency_sum,
        circuit_state=m.circuit_state,
        current_interval=m.current_interval,
    )
