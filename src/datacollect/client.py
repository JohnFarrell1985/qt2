"""智能 HTTP 客户端 — curl_cffi + UA 轮换 + tenacity 重试 + 反爬哨兵

封装 curl_cffi.requests.Session, 提供:
- 浏览器指纹模拟 (impersonate)
- User-Agent 自动轮换
- 指数退避 + 随机抖动重试 (含 HTTP 429/503)
- AntiCrawlSentinel 实时反爬检测
- 代理支持
- 线程安全的会话管理
"""
from __future__ import annotations

import threading
import time
from typing import Any

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)

_CFG = settings.datacollect


class _RetryableHTTPError(Exception):
    """可重试的 HTTP 错误 (429 Too Many Requests, 503 Service Unavailable 等)。"""

    def __init__(self, status_code: int, url: str = ""):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code} from {url}")


def _make_retry_decorator():
    """延迟构建 tenacity 重试装饰器, 覆盖网络异常 + 限流 HTTP 状态码。"""
    from tenacity import (
        retry,
        stop_after_attempt,
        wait_exponential_jitter,
        retry_if_exception_type,
        before_sleep_log,
    )
    import logging

    return retry(
        stop=stop_after_attempt(_CFG.max_retries),
        wait=wait_exponential_jitter(
            exp_base=_CFG.retry_backoff_base,
            jitter=2,
        ),
        retry=retry_if_exception_type(
            (ConnectionError, TimeoutError, OSError, _RetryableHTTPError),
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


_RETRYABLE_STATUS_CODES = frozenset({429, 503, 502, 520, 521, 522, 524})

_sentinel_instance = None
_sentinel_lock = threading.Lock()


def _get_sentinel():
    """全局共享 AntiCrawlSentinel 单例。"""
    global _sentinel_instance
    if _sentinel_instance is None:
        with _sentinel_lock:
            if _sentinel_instance is None:
                from src.datacollect.sentinel import AntiCrawlSentinel
                _sentinel_instance = AntiCrawlSentinel()
    return _sentinel_instance


class SmartHttpClient:
    """线程安全的 HTTP 客户端, 基于 curl_cffi 和浏览器指纹模拟。

    每个线程维护独立的 Session 实例以避免竞态条件。
    集成 AntiCrawlSentinel 检测反爬信号。
    """

    def __init__(
        self,
        impersonate: str = "",
        proxy_url: str = "",
        timeout: int = 0,
    ):
        self._impersonate = impersonate or _CFG.impersonate
        self._proxy_url = proxy_url or _CFG.proxy_url
        self._timeout = timeout or _CFG.request_timeout
        self._local = threading.local()
        self._retry = _make_retry_decorator()

    def _get_session(self):
        """获取当前线程的 curl_cffi Session (懒初始化)。"""
        session = getattr(self._local, "session", None)
        if session is None:
            from curl_cffi.requests import Session

            proxies = {"https": self._proxy_url, "http": self._proxy_url} if self._proxy_url else None
            session = Session(
                impersonate=self._impersonate,
                proxies=proxies,
                timeout=self._timeout,
            )
            self._local.session = session
            logger.debug("创建新 curl_cffi Session (impersonate=%s)", self._impersonate)
        return session

    def _rotate_ua(self, headers: dict[str, str] | None) -> dict[str, str]:
        """为请求注入随机 User-Agent。"""
        from fake_useragent import UserAgent

        ua = getattr(self._local, "ua", None)
        if ua is None:
            ua = UserAgent()
            self._local.ua = ua

        headers = dict(headers) if headers else {}
        if "User-Agent" not in headers:
            headers["User-Agent"] = ua.random
        return headers

    @staticmethod
    def _check_sentinel(url: str, status_code: int, latency: float, body_len: int, body_text: str = ""):
        """将响应信息送入 AntiCrawlSentinel 检测。"""
        try:
            from urllib.parse import urlparse
            from src.datacollect.sentinel import ResponseCheck
            domain = urlparse(url).netloc
            sentinel = _get_sentinel()
            sentinel.check_response(
                domain,
                ResponseCheck(
                    status_code=status_code,
                    latency=latency,
                    body_length=body_len,
                    body_text=body_text[:200],
                ),
            )
        except Exception:
            pass

    def get(
        self, url: str, *, headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None, skip_retry: bool = False, **kwargs,
    ) -> Any:
        """发送 GET 请求, 带重试、UA 轮换和反爬检测。

        ``skip_retry=True`` 时单次请求 (用于 K 线多源级联: 失败则换源, 不在此源上耗 tenacity)。
        """
        headers = self._rotate_ua(headers)

        def _do():
            session = self._get_session()
            t0 = time.monotonic()
            resp = session.get(url, headers=headers, params=params, **kwargs)
            latency = time.monotonic() - t0
            self._check_sentinel(url, resp.status_code, latency, len(resp.content))
            if resp.status_code in _RETRYABLE_STATUS_CODES:
                raise _RetryableHTTPError(resp.status_code, url)
            resp.raise_for_status()
            return resp

        if skip_retry:
            return _do()
        return self._retry(_do)()

    def post(
        self, url: str, *, headers: dict[str, str] | None = None,
        data: Any = None, json: Any = None, **kwargs,
    ) -> Any:
        """发送 POST 请求, 带重试、UA 轮换和反爬检测。"""
        headers = self._rotate_ua(headers)

        @self._retry
        def _do():
            session = self._get_session()
            t0 = time.monotonic()
            resp = session.post(url, headers=headers, data=data, json=json, **kwargs)
            latency = time.monotonic() - t0
            self._check_sentinel(url, resp.status_code, latency, len(resp.content))
            if resp.status_code in _RETRYABLE_STATUS_CODES:
                raise _RetryableHTTPError(resp.status_code, url)
            resp.raise_for_status()
            return resp

        return _do()

    def close(self) -> None:
        """关闭当前线程的 Session。"""
        session = getattr(self._local, "session", None)
        if session is not None:
            session.close()
            self._local.session = None
