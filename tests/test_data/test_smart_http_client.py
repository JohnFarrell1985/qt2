"""Tests for src/datacollect/client.py — SmartHttpClient"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.datacollect.client import SmartHttpClient, _RetryableHTTPError, _get_sentinel


# ====================================================================
# Fixtures
# ====================================================================

@pytest.fixture()
def mock_settings():
    """Patch _CFG with safe defaults."""
    cfg = MagicMock()
    cfg.impersonate = "chrome"
    cfg.proxy_url = ""
    cfg.request_timeout = 10
    cfg.max_retries = 3
    cfg.retry_backoff_base = 0.01
    with patch("src.datacollect.client._CFG", cfg):
        yield cfg


@pytest.fixture()
def mock_session():
    """Return a mock curl_cffi Session and its default response."""
    session = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.content = b"ok"
    resp.text = "ok"
    resp.raise_for_status = MagicMock()
    session.get = MagicMock(return_value=resp)
    session.post = MagicMock(return_value=resp)
    return session, resp


@pytest.fixture(autouse=True)
def _no_sentinel():
    """Prevent real AntiCrawlSentinel instantiation."""
    with patch.object(SmartHttpClient, "_check_sentinel", return_value=None):
        yield


@pytest.fixture(autouse=True)
def _reset_sentinel_singleton():
    """Reset the module-level sentinel singleton between tests."""
    import src.datacollect.client as mod
    original = mod._sentinel_instance
    mod._sentinel_instance = None
    yield
    mod._sentinel_instance = original


# ====================================================================
# Initialization
# ====================================================================

class TestInit:

    def test_defaults_from_config(self, mock_settings):
        client = SmartHttpClient()
        assert client._impersonate == "chrome"
        assert client._timeout == 10

    def test_override_params(self, mock_settings):
        client = SmartHttpClient(
            impersonate="firefox", proxy_url="http://p:8080", timeout=30,
        )
        assert client._impersonate == "firefox"
        assert client._proxy_url == "http://p:8080"
        assert client._timeout == 30


# ====================================================================
# GET / POST — 200 success
# ====================================================================

class TestGetPost:

    def test_get_returns_response(self, mock_settings, mock_session):
        session_mock, resp = mock_session
        client = SmartHttpClient()
        client._local.session = session_mock

        with patch.object(client, "_rotate_ua", return_value={"User-Agent": "test"}):
            result = client.get("http://api.test/data", params={"k": "v"})

        assert result is resp
        session_mock.get.assert_called_once()

    def test_post_returns_response(self, mock_settings, mock_session):
        session_mock, resp = mock_session
        client = SmartHttpClient()
        client._local.session = session_mock

        with patch.object(client, "_rotate_ua", return_value={}):
            result = client.post("http://api.test/submit", json={"field": "value"})

        assert result is resp
        session_mock.post.assert_called_once()


# ====================================================================
# Retry on HTTP 429 / 503
# ====================================================================

class TestRetryableStatus:

    def test_429_triggers_retry_then_succeeds(self, mock_settings, mock_session):
        session_mock, good_resp = mock_session

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.content = b""

        session_mock.get = MagicMock(side_effect=[resp_429, good_resp])

        client = SmartHttpClient()
        client._local.session = session_mock

        with patch.object(client, "_rotate_ua", return_value={}):
            result = client.get("http://api.test/data")

        assert result is good_resp
        assert session_mock.get.call_count == 2

    def test_503_triggers_retry_then_succeeds(self, mock_settings, mock_session):
        session_mock, good_resp = mock_session

        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.content = b""

        session_mock.get = MagicMock(side_effect=[resp_503, good_resp])

        client = SmartHttpClient()
        client._local.session = session_mock

        with patch.object(client, "_rotate_ua", return_value={}):
            result = client.get("http://api.test/data")

        assert result is good_resp
        assert session_mock.get.call_count == 2

    def test_retryable_http_error_fields(self):
        err = _RetryableHTTPError(429, "http://example.com")
        assert err.status_code == 429
        assert "429" in str(err)
        assert "example.com" in str(err)


# ====================================================================
# _check_sentinel is called per response
# ====================================================================

class TestSentinelIntegration:

    def test_check_sentinel_called_on_get(self, mock_settings, mock_session):
        session_mock, resp = mock_session
        client = SmartHttpClient()
        client._local.session = session_mock

        with patch.object(
            SmartHttpClient, "_check_sentinel", return_value=None,
        ) as mock_cs, patch.object(client, "_rotate_ua", return_value={}):
            client.get("http://api.test/data")

        mock_cs.assert_called_once()
        call_args = mock_cs.call_args
        assert call_args[0][0] == "http://api.test/data"
        assert call_args[0][1] == 200

    def test_check_sentinel_called_on_post(self, mock_settings, mock_session):
        session_mock, resp = mock_session
        client = SmartHttpClient()
        client._local.session = session_mock

        with patch.object(
            SmartHttpClient, "_check_sentinel", return_value=None,
        ) as mock_cs, patch.object(client, "_rotate_ua", return_value={}):
            client.post("http://api.test/submit", json={})

        mock_cs.assert_called_once()


# ====================================================================
# _get_sentinel singleton
# ====================================================================

class TestGetSentinel:

    def test_returns_anti_crawl_sentinel(self, mock_settings):
        with patch("src.datacollect.client.AntiCrawlSentinel", create=True) as mock_cls:
            mock_cls.return_value = MagicMock()
            import src.datacollect.client as mod
            mod._sentinel_instance = None
            with patch("src.datacollect.sentinel.AntiCrawlSentinel", mock_cls):
                sentinel = _get_sentinel()
            assert sentinel is mock_cls.return_value


# ====================================================================
# UA rotation
# ====================================================================

class TestUARotation:

    def test_injects_ua_when_missing(self, mock_settings):
        client = SmartHttpClient()
        with patch("fake_useragent.UserAgent") as ua_cls:
            ua_inst = MagicMock()
            ua_inst.random = "Mozilla/5.0 Test"
            ua_cls.return_value = ua_inst
            result = client._rotate_ua(None)
        assert result["User-Agent"] == "Mozilla/5.0 Test"

    def test_preserves_existing_ua(self, mock_settings):
        client = SmartHttpClient()
        headers = {"User-Agent": "Custom/1.0"}
        result = client._rotate_ua(headers)
        assert result["User-Agent"] == "Custom/1.0"
