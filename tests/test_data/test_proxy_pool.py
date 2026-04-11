"""Tests for src/datacollect/proxy_pool.py — A38"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from src.datacollect.proxy_pool import (
    AllProxiesBlacklisted,
    ProxyConfig,
    ProxyPoolManager,
    RotateStrategy,
)


# ====================================================================
# ProxyConfig
# ====================================================================

class TestProxyConfig:

    def test_ip_auto_extracted(self):
        pc = ProxyConfig(url="http://user:pass@1.2.3.4:8080")
        assert pc.ip == "1.2.3.4"

    def test_ip_from_hostname(self):
        pc = ProxyConfig(url="http://proxy.example.com:3128")
        assert pc.ip == "proxy.example.com"

    def test_explicit_ip(self):
        pc = ProxyConfig(url="http://x:y@9.8.7.6:1234", ip="custom-ip")
        assert pc.ip == "custom-ip"

    def test_as_dict(self):
        pc = ProxyConfig(url="http://p:8080")
        d = pc.as_dict()
        assert d == {"http": "http://p:8080", "https": "http://p:8080"}


# ====================================================================
# ProxyPoolManager — 基础
# ====================================================================

class TestPoolBasics:

    def test_empty_pool_disabled(self):
        pool = ProxyPoolManager(proxies=[])
        assert not pool.enabled
        assert pool.pool_size == 0

    def test_pool_with_proxies_enabled(self):
        proxies = [ProxyConfig(url="http://1.1.1.1:80")]
        pool = ProxyPoolManager(proxies=proxies)
        assert pool.enabled
        assert pool.pool_size == 1

    def test_available_count(self):
        proxies = [
            ProxyConfig(url="http://1.1.1.1:80"),
            ProxyConfig(url="http://2.2.2.2:80"),
        ]
        pool = ProxyPoolManager(proxies=proxies)
        assert pool.available_count == 2

    def test_get_stats(self):
        proxies = [ProxyConfig(url="http://1.1.1.1:80")]
        pool = ProxyPoolManager(proxies=proxies)
        stats = pool.get_stats()
        assert stats["enabled"] is True
        assert stats["total"] == 1
        assert stats["available"] == 1
        assert stats["blacklisted"] == 0
        assert stats["strategy"] == "round_robin"


# ====================================================================
# Round-robin rotation
# ====================================================================

class TestRoundRobin:

    @pytest.mark.asyncio
    async def test_rotation_order(self):
        proxies = [
            ProxyConfig(url="http://a:80", ip="a"),
            ProxyConfig(url="http://b:80", ip="b"),
            ProxyConfig(url="http://c:80", ip="c"),
        ]
        pool = ProxyPoolManager(
            proxies=proxies,
            default_rate=100.0,
            default_burst=100,
        )

        ips = []
        for _ in range(6):
            p = await pool.acquire("test.com")
            assert p is not None
            ips.append(p.ip)

        assert ips == ["a", "b", "c", "a", "b", "c"]


# ====================================================================
# Acquire — disabled / empty
# ====================================================================

class TestAcquireDisabled:

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self):
        pool = ProxyPoolManager(proxies=[])
        result = await pool.acquire("test.com")
        assert result is None


# ====================================================================
# Blacklisting
# ====================================================================

class TestBlacklist:

    @pytest.mark.asyncio
    async def test_blacklisted_proxy_skipped(self):
        proxies = [
            ProxyConfig(url="http://a:80", ip="a"),
            ProxyConfig(url="http://b:80", ip="b"),
        ]
        pool = ProxyPoolManager(
            proxies=proxies,
            default_rate=100.0,
            default_burst=100,
            blacklist_cooldown_sec=0.1,
        )

        p_a = await pool.acquire("test.com")
        assert p_a is not None and p_a.ip == "a"

        await pool.report_blocked(p_a)
        assert pool.blacklisted_count == 1
        assert pool.available_count == 1

        p_next = await pool.acquire("test.com")
        assert p_next is not None and p_next.ip == "b"

    @pytest.mark.asyncio
    async def test_all_blacklisted_raises(self):
        proxies = [ProxyConfig(url="http://a:80", ip="a")]
        pool = ProxyPoolManager(
            proxies=proxies,
            default_rate=100.0,
            default_burst=100,
            blacklist_cooldown_sec=999.0,
        )

        p = await pool.acquire("test.com")
        assert p is not None
        await pool.report_blocked(p)

        with pytest.raises(AllProxiesBlacklisted):
            await pool.acquire("test.com")

    @pytest.mark.asyncio
    async def test_blacklist_auto_recovery(self):
        proxies = [ProxyConfig(url="http://a:80", ip="a")]
        pool = ProxyPoolManager(
            proxies=proxies,
            default_rate=100.0,
            default_burst=100,
            blacklist_cooldown_sec=0.05,
        )

        p = await pool.acquire("test.com")
        assert p is not None
        await pool.report_blocked(p)
        assert pool.blacklisted_count == 1

        await asyncio.sleep(0.1)
        assert pool.blacklisted_count == 0

        p2 = await pool.acquire("test.com")
        assert p2 is not None and p2.ip == "a"


# ====================================================================
# Dynamic add / remove
# ====================================================================

class TestDynamicPoolManagement:

    def test_add_proxy(self):
        pool = ProxyPoolManager(proxies=[])
        assert not pool.enabled

        pool.add_proxy(ProxyConfig(url="http://new:80"))
        assert pool.enabled
        assert pool.pool_size == 1

    def test_remove_proxy(self):
        proxies = [
            ProxyConfig(url="http://a:80", ip="a"),
            ProxyConfig(url="http://b:80", ip="b"),
        ]
        pool = ProxyPoolManager(proxies=proxies)
        pool.remove_proxy("a")

        assert pool.pool_size == 1
        assert pool.enabled

    def test_remove_last_proxy_disables(self):
        proxies = [ProxyConfig(url="http://a:80", ip="a")]
        pool = ProxyPoolManager(proxies=proxies)
        pool.remove_proxy("a")

        assert pool.pool_size == 0
        assert not pool.enabled

    def test_remove_also_clears_blacklist(self):
        proxies = [ProxyConfig(url="http://a:80", ip="a")]
        pool = ProxyPoolManager(proxies=proxies)
        pool._blacklist.add("a")

        pool.remove_proxy("a")
        assert pool.blacklisted_count == 0


# ====================================================================
# Strategy
# ====================================================================

class TestStrategy:

    @pytest.mark.asyncio
    async def test_random_strategy(self):
        proxies = [
            ProxyConfig(url="http://a:80", ip="a"),
            ProxyConfig(url="http://b:80", ip="b"),
        ]
        pool = ProxyPoolManager(
            proxies=proxies,
            default_rate=100.0,
            default_burst=100,
            strategy=RotateStrategy.RANDOM,
        )

        results = set()
        for _ in range(20):
            p = await pool.acquire("test.com")
            assert p is not None
            results.add(p.ip)

        assert len(results) >= 1


# ====================================================================
# from_env (mocked config)
# ====================================================================

class TestFromEnv:

    def test_empty_proxy_urls(self):
        with patch("src.datacollect.proxy_pool.settings") as mock_s:
            mock_s.datacollect.proxy_urls = ""
            mock_s.datacollect.proxy_rotate_strategy = "round_robin"
            mock_s.datacollect.proxy_blacklist_cooldown = 600
            pool = ProxyPoolManager.from_env()
        assert not pool.enabled

    def test_with_proxy_urls(self):
        with patch("src.datacollect.proxy_pool.settings") as mock_s:
            mock_s.datacollect.proxy_urls = "http://a:80,http://b:80"
            mock_s.datacollect.proxy_rotate_strategy = "random"
            mock_s.datacollect.proxy_blacklist_cooldown = 300
            pool = ProxyPoolManager.from_env()
        assert pool.enabled
        assert pool.pool_size == 2
        assert pool._strategy == RotateStrategy.RANDOM
