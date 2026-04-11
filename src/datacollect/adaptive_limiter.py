"""自适应限流器 — 根据反爬反馈动态调整请求间隔

基于滑动窗口统计, 自动加速/降速:
- block_rate > 10% → 间隔 ×2
- block_rate > 5%  → 间隔 ×1.5
- avg_latency > 5s → 间隔 ×1.3
- 持续正常 10min  → 间隔 ×0.8 (不低于 base_interval)
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class RequestResult:
    """单次请求的结果摘要。"""
    status_code: int
    latency: float
    timestamp: float = field(default_factory=time.monotonic)


class AdaptiveLimiter:
    """根据实时反爬反馈动态调整请求间隔的限流器。

    Args:
        domain: 数据源域名标识
        base_interval: 基准请求间隔 (秒)
        window_sec: 统计滑动窗口长度 (秒)
        block_threshold: block_rate 触发 ×2 的阈值
        warn_threshold: block_rate 触发 ×1.5 的阈值
        speedup_after_sec: 持续正常后可加速的时间阈值 (秒)
        latency_spike_sec: 平均延迟超过此值时触发 ×1.3
    """

    _domain_instances: dict[str, AdaptiveLimiter] = {}
    _domain_lock = threading.Lock()

    def __init__(
        self,
        domain: str,
        base_interval: float,
        window_sec: float = 300.0,
        block_threshold: float = 0.10,
        warn_threshold: float = 0.05,
        speedup_after_sec: float = 600.0,
        latency_spike_sec: float = 5.0,
    ):
        self._domain = domain
        self._base_interval = base_interval
        self._current_interval = base_interval
        self._window_sec = window_sec
        self._block_threshold = block_threshold
        self._warn_threshold = warn_threshold
        self._speedup_after_sec = speedup_after_sec
        self._latency_spike_sec = latency_spike_sec

        self._results: list[RequestResult] = []
        self._last_block_time: float = 0.0
        self._retry_after_until: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 类方法: 按域单例
    # ------------------------------------------------------------------

    @classmethod
    def for_domain(
        cls,
        domain: str,
        base_interval: float,
        **kwargs,
    ) -> AdaptiveLimiter:
        """获取或创建指定域名的自适应限流器实例。"""
        with cls._domain_lock:
            if domain not in cls._domain_instances:
                cls._domain_instances[domain] = cls(
                    domain, base_interval, **kwargs,
                )
                logger.debug(
                    "为域 %s 创建自适应限流器 (base_interval=%.2f)",
                    domain, base_interval,
                )
            return cls._domain_instances[domain]

    @classmethod
    def reset_all(cls) -> None:
        """清空所有域实例 (测试用)。"""
        with cls._domain_lock:
            cls._domain_instances.clear()

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    def record(self, status_code: int, latency: float) -> None:
        """记录一次请求结果并触发自适应调整。"""
        now = time.monotonic()
        result = RequestResult(
            status_code=status_code, latency=latency, timestamp=now,
        )
        with self._lock:
            self._results.append(result)
            if status_code in (429, 403):
                self._last_block_time = now
            self._purge_old(now)
            self._adjust(now)

    def record_retry_after(self, seconds: float) -> None:
        """根据 Retry-After 头强制等待指定秒数。"""
        now = time.monotonic()
        with self._lock:
            self._retry_after_until = now + seconds
            new_interval = max(self._current_interval, seconds)
            if new_interval != self._current_interval:
                logger.info(
                    "[%s] Retry-After %.1fs → 间隔调整为 %.2fs",
                    self._domain, seconds, new_interval,
                )
                self._current_interval = new_interval

    def get_current_interval(self) -> float:
        """获取当前请求间隔 (秒), 考虑 Retry-After。"""
        with self._lock:
            now = time.monotonic()
            if now < self._retry_after_until:
                return max(
                    self._current_interval,
                    self._retry_after_until - now,
                )
            return self._current_interval

    # ------------------------------------------------------------------
    # 统计属性
    # ------------------------------------------------------------------

    @property
    def success_rate(self) -> float:
        with self._lock:
            self._purge_old(time.monotonic())
            if not self._results:
                return 1.0
            ok = sum(1 for r in self._results if 200 <= r.status_code < 400)
            return ok / len(self._results)

    @property
    def block_rate(self) -> float:
        with self._lock:
            self._purge_old(time.monotonic())
            if not self._results:
                return 0.0
            blocked = sum(
                1 for r in self._results if r.status_code in (429, 403)
            )
            return blocked / len(self._results)

    @property
    def avg_latency(self) -> float:
        with self._lock:
            self._purge_old(time.monotonic())
            if not self._results:
                return 0.0
            return sum(r.latency for r in self._results) / len(self._results)

    @property
    def timeout_rate(self) -> float:
        with self._lock:
            self._purge_old(time.monotonic())
            if not self._results:
                return 0.0
            timeouts = sum(1 for r in self._results if r.status_code == 0)
            return timeouts / len(self._results)

    # ------------------------------------------------------------------
    # 内部方法 (调用方持有 _lock)
    # ------------------------------------------------------------------

    def _purge_old(self, now: float) -> None:
        cutoff = now - self._window_sec
        self._results = [r for r in self._results if r.timestamp >= cutoff]

    def _adjust(self, now: float) -> None:
        if not self._results:
            return

        total = len(self._results)
        blocked = sum(1 for r in self._results if r.status_code in (429, 403))
        br = blocked / total

        prev = self._current_interval

        if br > self._block_threshold:
            self._current_interval *= 2.0
            logger.warning(
                "[%s] block_rate %.1f%% > %.0f%% → 间隔 ×2 → %.2fs",
                self._domain, br * 100, self._block_threshold * 100,
                self._current_interval,
            )
        elif br > self._warn_threshold:
            self._current_interval *= 1.5
            logger.warning(
                "[%s] block_rate %.1f%% > %.0f%% → 间隔 ×1.5 → %.2fs",
                self._domain, br * 100, self._warn_threshold * 100,
                self._current_interval,
            )
        else:
            avg_lat = sum(r.latency for r in self._results) / total
            if avg_lat > self._latency_spike_sec:
                self._current_interval *= 1.3
                logger.info(
                    "[%s] avg_latency %.2fs > %.1fs → 间隔 ×1.3 → %.2fs",
                    self._domain, avg_lat, self._latency_spike_sec,
                    self._current_interval,
                )
            elif (
                self._last_block_time > 0
                and (now - self._last_block_time) > self._speedup_after_sec
            ) or (
                self._last_block_time == 0
                and total >= 5
            ):
                new_interval = max(
                    self._base_interval,
                    self._current_interval * 0.8,
                )
                if new_interval < self._current_interval:
                    self._current_interval = new_interval
                    logger.info(
                        "[%s] 持续正常 → 间隔 ×0.8 → %.2fs",
                        self._domain, self._current_interval,
                    )

        if self._current_interval != prev:
            logger.debug(
                "[%s] 间隔从 %.2fs 调整为 %.2fs",
                self._domain, prev, self._current_interval,
            )
