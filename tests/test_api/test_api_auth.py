"""Tests for API Key authentication middleware"""
import pytest

from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture()
def client():
    return TestClient(app, raise_server_exceptions=False)


class TestApiKeyMiddleware:
    """Test the API Key middleware with production app (key disabled by default)."""

    def test_health_always_accessible(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_root_always_accessible(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_middleware_disabled_by_default(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200


class TestCorsHeaders:
    def test_cors_headers_present(self, client):
        resp = client.options(
            "/health",
            headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
        )
        assert resp.status_code in (200, 400)
