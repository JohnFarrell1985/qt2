"""Tests for src/datacollect/sentinel.py"""
from __future__ import annotations

import threading

import pytest

from src.datacollect.sentinel import (
    AntiCrawlSentinel,
    ResponseCheck,
    SentinelVerdict,
)


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture()
def sentinel() -> AntiCrawlSentinel:
    return AntiCrawlSentinel(
        latency_spike_sec=10.0,
        latency_warn_sec=5.0,
        soft_block_min_bytes=50,
        consecutive_timeout_limit=2,
    )


# ====================================================================
# 明确封禁
# ====================================================================

class TestBlocked:
    def test_429_returns_blocked(self, sentinel: AntiCrawlSentinel):
        resp = ResponseCheck(status_code=429, latency=0.5, body_length=100)
        assert sentinel.check_response("d", resp) == SentinelVerdict.BLOCKED

    def test_403_returns_blocked(self, sentinel: AntiCrawlSentinel):
        resp = ResponseCheck(status_code=403, latency=0.5, body_length=100)
        assert sentinel.check_response("d", resp) == SentinelVerdict.BLOCKED


# ====================================================================
# 软封禁
# ====================================================================

class TestSoftBlocked:
    def test_short_body_returns_soft_blocked(self, sentinel: AntiCrawlSentinel):
        resp = ResponseCheck(status_code=200, latency=0.3, body_length=10)
        assert sentinel.check_response("d", resp) == SentinelVerdict.SOFT_BLOCKED

    def test_captcha_text_returns_soft_blocked(self, sentinel: AntiCrawlSentinel):
        resp = ResponseCheck(
            status_code=200, latency=0.3, body_length=200,
            body_text="<html>请输入验证码</html>",
        )
        assert sentinel.check_response("d", resp) == SentinelVerdict.SOFT_BLOCKED

    def test_english_captcha_returns_soft_blocked(self, sentinel: AntiCrawlSentinel):
        resp = ResponseCheck(
            status_code=200, latency=0.3, body_length=200,
            body_text="<html>Please solve the captcha</html>",
        )
        assert sentinel.check_response("d", resp) == SentinelVerdict.SOFT_BLOCKED

    def test_retry_text_returns_soft_blocked(self, sentinel: AntiCrawlSentinel):
        resp = ResponseCheck(
            status_code=200, latency=0.3, body_length=200,
            body_text="请稍后再试",
        )
        assert sentinel.check_response("d", resp) == SentinelVerdict.SOFT_BLOCKED

    def test_zero_body_returns_soft_blocked(self, sentinel: AntiCrawlSentinel):
        resp = ResponseCheck(status_code=200, latency=0.3, body_length=0)
        assert sentinel.check_response("d", resp) == SentinelVerdict.SOFT_BLOCKED


# ====================================================================
# 延迟检测
# ====================================================================

class TestLatency:
    def test_spike_returns_suspected(self, sentinel: AntiCrawlSentinel):
        resp = ResponseCheck(status_code=200, latency=11.0, body_length=1000)
        assert sentinel.check_response("d", resp) == SentinelVerdict.SUSPECTED

    def test_consecutive_slow_returns_blocked(self, sentinel: AntiCrawlSentinel):
        resp1 = ResponseCheck(status_code=200, latency=6.0, body_length=1000)
        resp2 = ResponseCheck(status_code=200, latency=6.0, body_length=1000)
        sentinel.check_response("d", resp1)
        assert sentinel.check_response("d", resp2) == SentinelVerdict.BLOCKED

    def test_slow_then_fast_resets(self, sentinel: AntiCrawlSentinel):
        slow = ResponseCheck(status_code=200, latency=6.0, body_length=1000)
        fast = ResponseCheck(status_code=200, latency=0.5, body_length=1000)
        sentinel.check_response("d", slow)
        sentinel.check_response("d", fast)
        assert sentinel.check_response("d", slow) == SentinelVerdict.SUSPECTED


# ====================================================================
# 超时
# ====================================================================

class TestTimeout:
    def test_single_timeout_suspected(self, sentinel: AntiCrawlSentinel):
        resp = ResponseCheck(status_code=0, latency=0.0, body_length=0)
        assert sentinel.check_response("d", resp) == SentinelVerdict.SUSPECTED

    def test_consecutive_timeouts_returns_timeout(self, sentinel: AntiCrawlSentinel):
        resp = ResponseCheck(status_code=0, latency=0.0, body_length=0)
        sentinel.check_response("d", resp)
        assert sentinel.check_response("d", resp) == SentinelVerdict.TIMEOUT

    def test_timeout_resets_on_success(self, sentinel: AntiCrawlSentinel):
        timeout_resp = ResponseCheck(status_code=0, latency=0.0, body_length=0)
        ok_resp = ResponseCheck(status_code=200, latency=0.3, body_length=500)
        sentinel.check_response("d", timeout_resp)
        sentinel.check_response("d", ok_resp)
        assert sentinel.check_response("d", timeout_resp) == SentinelVerdict.SUSPECTED


# ====================================================================
# 正常响应
# ====================================================================

class TestOK:
    def test_normal_200_returns_ok(self, sentinel: AntiCrawlSentinel):
        resp = ResponseCheck(status_code=200, latency=0.3, body_length=500)
        assert sentinel.check_response("d", resp) == SentinelVerdict.OK

    def test_301_normal_body_returns_ok(self, sentinel: AntiCrawlSentinel):
        resp = ResponseCheck(status_code=301, latency=0.3, body_length=500)
        assert sentinel.check_response("d", resp) == SentinelVerdict.OK


# ====================================================================
# 5xx
# ====================================================================

class TestServerError:
    def test_500_returns_suspected(self, sentinel: AntiCrawlSentinel):
        resp = ResponseCheck(status_code=500, latency=0.3, body_length=200)
        assert sentinel.check_response("d", resp) == SentinelVerdict.SUSPECTED


# ====================================================================
# 域隔离
# ====================================================================

class TestDomainIsolation:
    def test_different_domains_independent(self, sentinel: AntiCrawlSentinel):
        timeout_resp = ResponseCheck(status_code=0, latency=0.0, body_length=0)
        sentinel.check_response("domain_a", timeout_resp)
        result = sentinel.check_response("domain_b", timeout_resp)
        assert result == SentinelVerdict.SUSPECTED

    def test_reset_only_affects_target(self, sentinel: AntiCrawlSentinel):
        timeout_resp = ResponseCheck(status_code=0, latency=0.0, body_length=0)
        sentinel.check_response("a", timeout_resp)
        sentinel.check_response("b", timeout_resp)
        sentinel.reset("a")
        result_a = sentinel.check_response("a", timeout_resp)
        result_b = sentinel.check_response("b", timeout_resp)
        assert result_a == SentinelVerdict.SUSPECTED
        assert result_b == SentinelVerdict.TIMEOUT


# ====================================================================
# 历史记录
# ====================================================================

class TestHistory:
    def test_get_recent_verdicts(self, sentinel: AntiCrawlSentinel):
        resp = ResponseCheck(status_code=200, latency=0.3, body_length=500)
        sentinel.check_response("d", resp)
        sentinel.check_response("d", resp)
        verdicts = sentinel.get_recent_verdicts("d")
        assert verdicts == [SentinelVerdict.OK, SentinelVerdict.OK]

    def test_unknown_domain_empty(self, sentinel: AntiCrawlSentinel):
        assert sentinel.get_recent_verdicts("unknown") == []

    def test_history_capped(self):
        sentinel = AntiCrawlSentinel(history_size=3)
        resp = ResponseCheck(status_code=200, latency=0.3, body_length=500)
        for _ in range(5):
            sentinel.check_response("d", resp)
        assert len(sentinel.get_recent_verdicts("d")) == 3


# ====================================================================
# 线程安全
# ====================================================================

class TestThreadSafety:
    def test_concurrent_checks(self, sentinel: AntiCrawlSentinel):
        errors: list[Exception] = []

        def worker():
            try:
                for i in range(50):
                    resp = ResponseCheck(
                        status_code=200, latency=0.3, body_length=500,
                    )
                    sentinel.check_response("d", resp)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        verdicts = sentinel.get_recent_verdicts("d")
        assert len(verdicts) > 0
