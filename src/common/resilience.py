"""系统级容错 & 降级

实现 Circuit Breaker 模式和降级管理。
基于 tenacity (已在 deps) 的扩展。

References:
  - Martin Fowler: Circuit Breaker Pattern
  - Resilience4j Design Patterns
"""
import time
import threading
from enum import Enum
from typing import Any, Callable, Optional

from tenacity import retry, stop_after_attempt, wait_exponential

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Thread-safe circuit breaker.

    States:
      CLOSED  → normal operation, tracks consecutive failures
      OPEN    → reject all calls, wait for recovery_timeout
      HALF_OPEN → allow up to half_open_max probe calls
    """

    def __init__(
        self,
        failure_threshold: int = None,
        recovery_timeout: float = None,
        half_open_max: int = 1,
    ):
        cfg = settings.resilience
        self._failure_threshold = failure_threshold or cfg.circuit_breaker_threshold
        self._recovery_timeout = recovery_timeout or cfg.recovery_timeout_sec
        self._half_open_max = half_open_max

        self._lock = threading.Lock()
        self._failure_count = 0
        self._success_count = 0
        self._half_open_calls = 0
        self._state = CircuitState.CLOSED
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if self._state == CircuitState.OPEN:
                if time.monotonic() - self._last_failure_time >= self._recovery_timeout:
                    self._state = CircuitState.HALF_OPEN
                    self._half_open_calls = 0
                    logger.info("Circuit breaker → HALF_OPEN (recovery timeout elapsed)")
            return self._state

    def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute func with circuit breaker protection."""
        current_state = self.state

        if current_state == CircuitState.OPEN:
            raise CircuitOpenError(
                f"Circuit breaker is OPEN (failures={self._failure_count})"
            )

        if current_state == CircuitState.HALF_OPEN:
            with self._lock:
                if self._half_open_calls >= self._half_open_max:
                    raise CircuitOpenError("Circuit breaker HALF_OPEN: max probes reached")
                self._half_open_calls += 1

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise

    def record_success(self) -> None:
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= 1:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("Circuit breaker → CLOSED (recovery success)")
            else:
                self._failure_count = 0

    def record_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning("Circuit breaker → OPEN (half-open probe failed)")
            elif self._failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker → OPEN (failures=%d >= threshold=%d)",
                    self._failure_count,
                    self._failure_threshold,
                )

    def reset(self) -> None:
        with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._success_count = 0
            self._half_open_calls = 0
            self._last_failure_time = 0.0


class CircuitOpenError(Exception):
    """Raised when circuit breaker is OPEN and rejects the call."""


class DegradationLevel(str, Enum):
    NORMAL = "normal"
    DEGRADED_DATA = "degraded_data"
    DEGRADED_TRADE = "degraded_trade"
    EMERGENCY = "emergency"


_SERVICE_AVAILABILITY: dict[DegradationLevel, set[str]] = {
    DegradationLevel.NORMAL: {"data", "trade", "backtest", "api"},
    DegradationLevel.DEGRADED_DATA: {"trade", "api"},
    DegradationLevel.DEGRADED_TRADE: {"data", "backtest", "api"},
    DegradationLevel.EMERGENCY: set(),
}


class DegradationManager:
    """Singleton degradation manager."""

    _instance: Optional["DegradationManager"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "DegradationManager":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._level = DegradationLevel.NORMAL
                cls._instance._listeners: list[Callable] = []
        return cls._instance

    @property
    def level(self) -> DegradationLevel:
        return self._level

    def set_level(self, level: DegradationLevel, reason: str = "") -> None:
        old = self._level
        self._level = level
        if old != level:
            logger.warning(
                "Degradation level: %s → %s | reason: %s",
                old.value, level.value, reason or "n/a",
            )
            for cb in self._listeners:
                try:
                    cb(old, level, reason)
                except Exception:
                    logger.exception("Degradation listener error")

    def is_available(self, service: str) -> bool:
        available = _SERVICE_AVAILABILITY.get(self._level, set())
        return service in available

    def on_change(self, callback: Callable) -> None:
        self._listeners.append(callback)

    def reset(self) -> None:
        self._level = DegradationLevel.NORMAL
        self._listeners.clear()

    @classmethod
    def _reset_singleton(cls) -> None:
        """Reset singleton for testing only."""
        with cls._lock:
            cls._instance = None


def resilient_call(
    func: Callable,
    fallback: Any = None,
    breaker: CircuitBreaker = None,
    max_retries: int = 3,
    **retry_kwargs: Any,
) -> Any:
    """Convenience wrapper combining circuit breaker + retry + fallback.

    If breaker is open, fallback is returned directly.
    On repeated failure after retries, fallback is returned.
    """
    def _execute() -> Any:
        if breaker is not None:
            return breaker.call(func)
        return func()

    @retry(
        stop=stop_after_attempt(max_retries),
        wait=wait_exponential(multiplier=0.5, min=0.1, max=5),
        reraise=True,
    )
    def _with_retry() -> Any:
        return _execute()

    try:
        return _with_retry()
    except CircuitOpenError:
        logger.warning("resilient_call: circuit open, using fallback")
        return fallback
    except Exception:
        logger.warning("resilient_call: all retries exhausted, using fallback")
        return fallback
