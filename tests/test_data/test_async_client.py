"""Tests for src/datacollect/async_client.py — A31"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.datacollect.async_client import AsyncSmartHttpClient


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture()
def mock_settings():
    """Patch settings.datacollect with safe defaults."""
    cfg = MagicMock()
    cfg.impersonate = "chrome"
    cfg.proxy_url = ""
    cfg.request_timeout = 10
    cfg.max_retries = 2
    cfg.retry_backoff_base = 1.0
    with patch("src.datacollect.async_client._CFG", cfg):
        yield cfg


@pytest.fixture()
def mock_async_session():
    """Return a mock AsyncSession factory."""
    session = AsyncMock()
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"ok": True}
    resp.text = "ok"
    session.get = AsyncMock(return_value=resp)
    session.post = AsyncMock(return_value=resp)
    session.close = AsyncMock()
    return session, resp


# ====================================================================
# Initialization
# ====================================================================

class TestInit:

    def test_defaults_from_config(self, mock_settings):
        client = AsyncSmartHttpClient()
        assert client._impersonate == "chrome"
        assert client._timeout == 10

    def test_override_params(self, mock_settings):
        client = AsyncSmartHttpClient(
            impersonate="firefox", proxy_url="http://p:8080", timeout=30,
        )
        assert client._impersonate == "firefox"
        assert client._proxy_url == "http://p:8080"
        assert client._timeout == 30


# ====================================================================
# Session 懒初始化
# ====================================================================

class TestSessionInit:

    @pytest.mark.asyncio
    async def test_lazy_session_creation(self, mock_settings, mock_async_session):
        session_mock, _ = mock_async_session
        client = AsyncSmartHttpClient()
        assert client._session is None

        with patch(
            "src.datacollect.async_client.AsyncSmartHttpClient._inject_ua",
            new_callable=lambda: AsyncMock(return_value={}),
        ), patch(
            "curl_cffi.requests.AsyncSession",
            return_value=session_mock,
        ):
            await client.get("http://example.com")

        assert client._session is session_mock

    @pytest.mark.asyncio
    async def test_session_reused(self, mock_settings, mock_async_session):
        session_mock, _ = mock_async_session
        client = AsyncSmartHttpClient()
        client._session = session_mock

        with patch(
            "src.datacollect.async_client.AsyncSmartHttpClient._inject_ua",
            new_callable=lambda: AsyncMock(return_value={}),
        ):
            await client.get("http://a.com")
            await client.get("http://b.com")

        assert session_mock.get.call_count == 2


# ====================================================================
# GET / POST
# ====================================================================

class TestGetPost:

    @pytest.mark.asyncio
    async def test_get_returns_response(self, mock_settings, mock_async_session):
        session_mock, resp = mock_async_session
        client = AsyncSmartHttpClient()
        client._session = session_mock

        with patch(
            "src.datacollect.async_client.AsyncSmartHttpClient._inject_ua",
            new_callable=lambda: AsyncMock(return_value={"User-Agent": "test"}),
        ):
            result = await client.get("http://api.test/data", params={"k": "v"})

        assert result is resp
        session_mock.get.assert_awaited_once()
        call_kwargs = session_mock.get.call_args
        assert call_kwargs.kwargs.get("params") == {"k": "v"} or call_kwargs[1].get("params") == {"k": "v"}

    @pytest.mark.asyncio
    async def test_post_returns_response(self, mock_settings, mock_async_session):
        session_mock, resp = mock_async_session
        client = AsyncSmartHttpClient()
        client._session = session_mock

        with patch(
            "src.datacollect.async_client.AsyncSmartHttpClient._inject_ua",
            new_callable=lambda: AsyncMock(return_value={}),
        ):
            result = await client.post(
                "http://api.test/submit",
                json={"field": "value"},
            )

        assert result is resp
        session_mock.post.assert_awaited_once()


# ====================================================================
# Proxy 解析
# ====================================================================

class TestProxyResolution:

    @pytest.mark.asyncio
    async def test_no_proxy_returns_none(self, mock_settings):
        client = AsyncSmartHttpClient()
        proxy = await client._resolve_proxy("example.com")
        assert proxy is None

    @pytest.mark.asyncio
    async def test_static_proxy(self, mock_settings):
        client = AsyncSmartHttpClient()
        client._proxy_url = "http://proxy:8080"
        proxy = await client._resolve_proxy("example.com")
        assert proxy == "http://proxy:8080"

    @pytest.mark.asyncio
    async def test_proxy_pool_integration(self, mock_settings):
        pool = AsyncMock()
        proxy_cfg = MagicMock()
        proxy_cfg.url = "http://pool-proxy:9090"
        pool.acquire = AsyncMock(return_value=proxy_cfg)

        client = AsyncSmartHttpClient(proxy_pool=pool)
        proxy = await client._resolve_proxy("example.com")

        assert proxy == "http://pool-proxy:9090"
        pool.acquire.assert_awaited_once_with("example.com")

    @pytest.mark.asyncio
    async def test_proxy_pool_returns_none(self, mock_settings):
        pool = AsyncMock()
        pool.acquire = AsyncMock(return_value=None)

        client = AsyncSmartHttpClient(proxy_pool=pool)
        proxy = await client._resolve_proxy("example.com")

        assert proxy is None


# ====================================================================
# UA 注入
# ====================================================================

class TestUAInjection:

    @pytest.mark.asyncio
    async def test_injects_ua_when_missing(self, mock_settings):
        client = AsyncSmartHttpClient()
        with patch("fake_useragent.UserAgent") as ua_cls:
            ua_inst = MagicMock()
            ua_inst.random = "Mozilla/5.0 Test"
            ua_cls.return_value = ua_inst

            result = client._inject_ua(None)

        assert result["User-Agent"] == "Mozilla/5.0 Test"

    @pytest.mark.asyncio
    async def test_preserves_existing_ua(self, mock_settings):
        client = AsyncSmartHttpClient()
        headers = {"User-Agent": "Custom/1.0"}
        result = client._inject_ua(headers)
        assert result["User-Agent"] == "Custom/1.0"

    @pytest.mark.asyncio
    async def test_does_not_mutate_input(self, mock_settings):
        client = AsyncSmartHttpClient()
        original = {"Accept": "application/json"}
        with patch("fake_useragent.UserAgent") as ua_cls:
            ua_cls.return_value.random = "UA"
            client._inject_ua(original)
        assert "User-Agent" not in original


# ====================================================================
# Context manager
# ====================================================================

class TestContextManager:

    @pytest.mark.asyncio
    async def test_aenter_aexit(self, mock_settings, mock_async_session):
        session_mock, _ = mock_async_session
        client = AsyncSmartHttpClient()
        client._session = session_mock

        async with client as c:
            assert c is client

        session_mock.close.assert_awaited_once()
        assert client._session is None

    @pytest.mark.asyncio
    async def test_close_idempotent(self, mock_settings):
        client = AsyncSmartHttpClient()
        await client.close()
        await client.close()
