"""异步 HTTP 客户端 — curl_cffi AsyncSession + tenacity AsyncRetrying

封装 curl_cffi.requests.AsyncSession, 提供:
- 浏览器指纹模拟 (impersonate)
- User-Agent 自动轮换
- 指数退避 + 随机抖动异步重试
- 代理池集成 (ProxyPoolManager)
- 双重检查锁的会话初始化
"""
from __future__ import annotations

import asyncio
from typing import Any

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)
_CFG = settings.datacollect


class AsyncSmartHttpClient:
    """异步 HTTP 客户端, 基于 curl_cffi AsyncSession。

    单个 AsyncSession 处理所有并发请求 (无需 threading.local)。
    可选集成 ProxyPoolManager 进行代理轮换。
    """

    def __init__(
        self,
        impersonate: str = "",
        proxy_url: str = "",
        timeout: int = 0,
        proxy_pool: Any = None,
    ):
        self._impersonate = impersonate or _CFG.impersonate
        self._proxy_url = proxy_url or _CFG.proxy_url
        self._timeout = timeout or _CFG.request_timeout
        self._proxy_pool = proxy_pool
        self._session: Any = None
        self._lock = asyncio.Lock()

    async def _get_session(self) -> Any:
        """双重检查锁的懒初始化 AsyncSession。"""
        if self._session is None:
            async with self._lock:
                if self._session is None:
                    from curl_cffi.requests import AsyncSession

                    self._session = AsyncSession(
                        impersonate=self._impersonate,
                        timeout=self._timeout,
                    )
                    logger.debug(
                        "创建 AsyncSession (impersonate=%s)", self._impersonate,
                    )
        return self._session

    def _make_async_retry(self) -> Any:
        """延迟构建 tenacity AsyncRetrying 实例。"""
        from tenacity import (
            AsyncRetrying,
            retry_if_exception_type,
            stop_after_attempt,
            wait_exponential_jitter,
        )

        return AsyncRetrying(
            stop=stop_after_attempt(_CFG.max_retries),
            wait=wait_exponential_jitter(
                exp_base=_CFG.retry_backoff_base, jitter=2,
            ),
            retry=retry_if_exception_type(
                (ConnectionError, TimeoutError, OSError),
            ),
            reraise=True,
        )

    async def get(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        domain: str = "",
        **kwargs: Any,
    ) -> Any:
        """发送异步 GET 请求, 带重试、UA 轮换和代理支持。"""
        session = await self._get_session()
        headers = self._inject_ua(headers)
        proxy = await self._resolve_proxy(domain)

        async for attempt in self._make_async_retry():
            with attempt:
                resp = await session.get(
                    url, headers=headers, params=params, proxy=proxy, **kwargs,
                )
                resp.raise_for_status()
                return resp

    async def post(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        data: Any = None,
        json: Any = None,
        domain: str = "",
        **kwargs: Any,
    ) -> Any:
        """发送异步 POST 请求, 带重试、UA 轮换和代理支持。"""
        session = await self._get_session()
        headers = self._inject_ua(headers)
        proxy = await self._resolve_proxy(domain)

        async for attempt in self._make_async_retry():
            with attempt:
                resp = await session.post(
                    url,
                    headers=headers,
                    data=data,
                    json=json,
                    proxy=proxy,
                    **kwargs,
                )
                resp.raise_for_status()
                return resp

    async def _resolve_proxy(self, domain: str) -> str | None:
        """根据代理池或静态配置获取代理 URL。"""
        if self._proxy_pool and domain:
            proxy_cfg = await self._proxy_pool.acquire(domain)
            return proxy_cfg.url if proxy_cfg else None
        if self._proxy_url:
            return self._proxy_url
        return None

    def _inject_ua(
        self, headers: dict[str, str] | None,
    ) -> dict[str, str]:
        """为请求注入随机 User-Agent。"""
        headers = dict(headers) if headers else {}
        if "User-Agent" not in headers:
            from fake_useragent import UserAgent

            ua = UserAgent()
            headers["User-Agent"] = ua.random
        return headers

    async def close(self) -> None:
        """关闭底层 AsyncSession。"""
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def __aenter__(self) -> AsyncSmartHttpClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
