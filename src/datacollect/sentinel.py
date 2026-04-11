"""反爬哨兵 — 实时检测反爬信号并发出分级判定

检测信号:
  429/403          → BLOCKED
  200 + 极短 body  → SOFT_BLOCKED
  200 + 验证码关键词 → SOFT_BLOCKED
  延迟 >10s        → SUSPECTED
  连续 2 次延迟 >5s → BLOCKED
  连续 2 次超时     → TIMEOUT
"""
from __future__ import annotations

import enum
import re
import threading
from dataclasses import dataclass, field

from src.common.logger import get_logger

logger = get_logger(__name__)

_SOFT_BLOCK_PATTERNS = re.compile(
    r"验证码|captcha|请稍后再试|频繁|too many requests",
    re.IGNORECASE,
)


class SentinelVerdict(enum.Enum):
    OK = "ok"
    SUSPECTED = "suspected"
    BLOCKED = "blocked"
    SOFT_BLOCKED = "soft_blocked"
    TIMEOUT = "timeout"


@dataclass
class ResponseCheck:
    """待检测的响应摘要。"""
    status_code: int
    latency: float
    body_length: int
    body_text: str = ""


@dataclass
class _DomainState:
    """单个域名的检测状态。"""
    consecutive_slow: int = 0
    consecutive_timeout: int = 0
    recent_checks: list[SentinelVerdict] = field(default_factory=list)


class AntiCrawlSentinel:
    """实时反爬检测哨兵。

    Args:
        latency_spike_sec: 单次延迟超过此值判定为 SUSPECTED
        latency_warn_sec: 连续超过此值 consecutive 次判定为 BLOCKED
        soft_block_min_bytes: body 长度低于此值 (且 status=200) 判定为 SOFT_BLOCKED
        consecutive_timeout_limit: 连续超时次数达到此值判定为 TIMEOUT
        history_size: 每域保留的最近检测记录数
    """

    def __init__(
        self,
        latency_spike_sec: float = 10.0,
        latency_warn_sec: float = 5.0,
        soft_block_min_bytes: int = 50,
        consecutive_timeout_limit: int = 2,
        history_size: int = 50,
    ):
        self._latency_spike_sec = latency_spike_sec
        self._latency_warn_sec = latency_warn_sec
        self._soft_block_min_bytes = soft_block_min_bytes
        self._consecutive_timeout_limit = consecutive_timeout_limit
        self._history_size = history_size

        self._domains: dict[str, _DomainState] = {}
        self._lock = threading.Lock()

    def check_response(
        self,
        domain: str,
        response: ResponseCheck,
    ) -> SentinelVerdict:
        """检查响应, 返回判定结果。"""
        with self._lock:
            state = self._get_or_create(domain)
            verdict = self._evaluate(state, response)

            state.recent_checks.append(verdict)
            if len(state.recent_checks) > self._history_size:
                state.recent_checks = state.recent_checks[-self._history_size:]

            if verdict not in (SentinelVerdict.OK, SentinelVerdict.SUSPECTED):
                logger.warning(
                    "[%s] 反爬判定: %s (status=%d, latency=%.2fs, body=%d bytes)",
                    domain, verdict.value, response.status_code,
                    response.latency, response.body_length,
                )

            return verdict

    def reset(self, domain: str) -> None:
        """重置指定域的检测状态。"""
        with self._lock:
            if domain in self._domains:
                self._domains[domain] = _DomainState()
                logger.info("[%s] 哨兵状态已重置", domain)

    def get_recent_verdicts(
        self, domain: str,
    ) -> list[SentinelVerdict]:
        """获取域名的最近判定历史。"""
        with self._lock:
            state = self._domains.get(domain)
            if state is None:
                return []
            return list(state.recent_checks)

    # ------------------------------------------------------------------
    # 内部 (调用方持有 _lock)
    # ------------------------------------------------------------------

    def _get_or_create(self, domain: str) -> _DomainState:
        if domain not in self._domains:
            self._domains[domain] = _DomainState()
        return self._domains[domain]

    def _evaluate(
        self,
        state: _DomainState,
        resp: ResponseCheck,
    ) -> SentinelVerdict:
        # status_code == 0 表示超时/连接失败
        if resp.status_code == 0:
            state.consecutive_slow = 0
            state.consecutive_timeout += 1
            if state.consecutive_timeout >= self._consecutive_timeout_limit:
                return SentinelVerdict.TIMEOUT
            return SentinelVerdict.SUSPECTED

        state.consecutive_timeout = 0

        if resp.status_code in (429, 403):
            state.consecutive_slow = 0
            return SentinelVerdict.BLOCKED

        if resp.status_code >= 500:
            state.consecutive_slow = 0
            return SentinelVerdict.SUSPECTED

        if 200 <= resp.status_code < 400:
            if resp.body_length < self._soft_block_min_bytes:
                state.consecutive_slow = 0
                return SentinelVerdict.SOFT_BLOCKED

            if resp.body_text and _SOFT_BLOCK_PATTERNS.search(resp.body_text):
                state.consecutive_slow = 0
                return SentinelVerdict.SOFT_BLOCKED

            if resp.latency > self._latency_warn_sec:
                state.consecutive_slow += 1
                if state.consecutive_slow >= 2:
                    return SentinelVerdict.BLOCKED
                if resp.latency > self._latency_spike_sec:
                    return SentinelVerdict.SUSPECTED
                return SentinelVerdict.SUSPECTED

            state.consecutive_slow = 0
            return SentinelVerdict.OK

        state.consecutive_slow = 0
        return SentinelVerdict.SUSPECTED
