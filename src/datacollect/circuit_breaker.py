"""三态熔断器 — 防止持续请求已失败的数据源

状态流转:
  CLOSED → OPEN:     连续失败达到 failure_threshold
  OPEN → HALF_OPEN:  冷却时间 cooldown_sec 后
  HALF_OPEN → CLOSED: 连续成功达到 success_threshold
  HALF_OPEN → OPEN:   任意一次失败 (冷却时间翻倍)
"""
from __future__ import annotations

import enum
import threading
import time

from src.common.logger import get_logger

logger = get_logger(__name__)


class CircuitState(enum.Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """线程安全的三态熔断器。

    Args:
        name: 熔断器名称 (通常为域名)
        failure_threshold: 连续失败多少次后触发熔断
        cooldown_sec: 熔断后冷却秒数
        success_threshold: 半开状态需要连续成功多少次才恢复
    """

    _domain_instances: dict[str, CircuitBreaker] = {}
    _domain_lock = threading.Lock()

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown_sec: float = 300.0,
        success_threshold: int = 2,
    ):
        self._name = name
        self._failure_threshold = failure_threshold
        self._base_cooldown = cooldown_sec
        self._cooldown_sec = cooldown_sec
        self._success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._consecutive_failures = 0
        self._consecutive_successes = 0
        self._opened_at: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 类方法: 按域单例
    # ------------------------------------------------------------------

    @classmethod
    def for_domain(cls, domain: str, **kwargs) -> CircuitBreaker:
        """获取或创建指定域名的熔断器实例。"""
        with cls._domain_lock:
            if domain not in cls._domain_instances:
                cls._domain_instances[domain] = cls(name=domain, **kwargs)
                logger.debug("为域 %s 创建熔断器", domain)
            return cls._domain_instances[domain]

    @classmethod
    def reset_all(cls) -> None:
        """清空所有域实例 (测试用)。"""
        with cls._domain_lock:
            cls._domain_instances.clear()

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    @property
    def state(self) -> CircuitState:
        with self._lock:
            self._maybe_transition_to_half_open()
            return self._state

    @property
    def name(self) -> str:
        return self._name

    def allow_request(self) -> bool:
        """判断是否允许发出请求。"""
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state == CircuitState.CLOSED:
                return True
            if self._state == CircuitState.HALF_OPEN:
                return True
            return False

    # ------------------------------------------------------------------
    # 结果记录
    # ------------------------------------------------------------------

    def record_success(self) -> None:
        """记录一次成功请求。"""
        with self._lock:
            self._maybe_transition_to_half_open()
            if self._state == CircuitState.CLOSED:
                self._consecutive_failures = 0
                return

            if self._state == CircuitState.HALF_OPEN:
                self._consecutive_successes += 1
                if self._consecutive_successes >= self._success_threshold:
                    self._state = CircuitState.CLOSED
                    self._consecutive_failures = 0
                    self._consecutive_successes = 0
                    self._cooldown_sec = self._base_cooldown
                    logger.info(
                        "[%s] 熔断器恢复 CLOSED (连续成功 %d 次)",
                        self._name, self._success_threshold,
                    )

    def record_failure(self) -> None:
        """记录一次失败请求。"""
        with self._lock:
            self._maybe_transition_to_half_open()

            if self._state == CircuitState.HALF_OPEN:
                self._cooldown_sec *= 2
                self._state = CircuitState.OPEN
                self._opened_at = time.monotonic()
                self._consecutive_successes = 0
                logger.warning(
                    "[%s] HALF_OPEN 失败 → OPEN (冷却翻倍 → %.0fs)",
                    self._name, self._cooldown_sec,
                )
                return

            if self._state == CircuitState.CLOSED:
                self._consecutive_failures += 1
                if self._consecutive_failures >= self._failure_threshold:
                    self._state = CircuitState.OPEN
                    self._opened_at = time.monotonic()
                    logger.warning(
                        "[%s] 连续失败 %d 次 → OPEN (冷却 %.0fs)",
                        self._name, self._consecutive_failures,
                        self._cooldown_sec,
                    )

    # ------------------------------------------------------------------
    # 手动控制
    # ------------------------------------------------------------------

    def force_open(self) -> None:
        """外部强制熔断 (如 Sentinel 检测到封禁)。"""
        with self._lock:
            self._state = CircuitState.OPEN
            self._opened_at = time.monotonic()
            self._consecutive_successes = 0
            logger.warning("[%s] 外部强制熔断 → OPEN", self._name)

    def reset(self) -> None:
        """重置为初始关闭状态。"""
        with self._lock:
            self._state = CircuitState.CLOSED
            self._consecutive_failures = 0
            self._consecutive_successes = 0
            self._cooldown_sec = self._base_cooldown
            self._opened_at = 0.0
            logger.info("[%s] 熔断器已重置", self._name)

    # ------------------------------------------------------------------
    # 内部 (调用方持有 _lock)
    # ------------------------------------------------------------------

    def _maybe_transition_to_half_open(self) -> None:
        if self._state != CircuitState.OPEN:
            return
        elapsed = time.monotonic() - self._opened_at
        if elapsed >= self._cooldown_sec:
            self._state = CircuitState.HALF_OPEN
            self._consecutive_successes = 0
            logger.info(
                "[%s] 冷却 %.0fs 结束 → HALF_OPEN",
                self._name, self._cooldown_sec,
            )
