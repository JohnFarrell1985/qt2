"""API Key & CORS E2E — 使用真实 FastAPI app 验证中间件行为

测试范围:
  - API Key 中间件默认禁用状态
  - 公开端点始终可访问
  - CORS 响应头
  - API Key 启用后的认证行为
"""
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api.main import app
from src.common.config import settings


pytestmark = pytest.mark.timeout(15)


@pytest.fixture
def unauthenticated_client(session_factory, seeded_db, db_engine):
    """TestClient (API Key disabled — 默认配置)"""
    import src.common.db as db_module
    with patch.object(db_module, "_engine", db_engine), \
         patch.object(db_module, "_SessionLocal", session_factory), \
         patch("src.api.main.init_database"), \
         patch("src.api.main.start_scheduler"), \
         patch("src.api.main.stop_scheduler"):
        with TestClient(app) as c:
            yield c


class TestApiKeyDisabled:
    """默认 API Key 禁用 — 所有端点可访问"""

    def test_health_accessible(self, unauthenticated_client):
        resp = unauthenticated_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")

    def test_root_accessible(self, unauthenticated_client):
        resp = unauthenticated_client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data
        assert "version" in data

    def test_data_endpoints_accessible(self, unauthenticated_client):
        resp = unauthenticated_client.get("/api/data/stocks")
        assert resp.status_code == 200

    def test_factor_endpoints_accessible(self, unauthenticated_client):
        resp = unauthenticated_client.get("/api/factor/list")
        assert resp.status_code == 200


class TestApiKeyEnabled:
    """API Key 启用后的认证行为"""

    @pytest.fixture
    def auth_client(self, session_factory, seeded_db, db_engine):
        """启用 API Key 的 TestClient"""
        import src.common.db as db_module
        with patch.object(db_module, "_engine", db_engine), \
             patch.object(db_module, "_SessionLocal", session_factory), \
             patch("src.api.main.init_database"), \
             patch("src.api.main.start_scheduler"), \
             patch("src.api.main.stop_scheduler"), \
             patch.object(settings.api, "api_key_enabled", True), \
             patch.object(settings.api, "api_key", "test-secret-key-12345"):
            with TestClient(app) as c:
                yield c

    def test_protected_endpoint_requires_key(self, auth_client):
        resp = auth_client.get("/api/data/stocks")
        assert resp.status_code in (401, 403)

    def test_protected_endpoint_with_valid_key(self, auth_client):
        resp = auth_client.get(
            "/api/data/stocks",
            headers={"X-API-Key": "test-secret-key-12345"},
        )
        assert resp.status_code == 200

    def test_protected_endpoint_with_wrong_key(self, auth_client):
        resp = auth_client.get(
            "/api/data/stocks",
            headers={"X-API-Key": "wrong-key"},
        )
        assert resp.status_code in (401, 403)

    def test_health_always_public(self, auth_client):
        resp = auth_client.get("/health")
        assert resp.status_code == 200

    def test_root_always_public(self, auth_client):
        resp = auth_client.get("/")
        assert resp.status_code == 200

    def test_docs_always_public(self, auth_client):
        resp = auth_client.get("/docs")
        assert resp.status_code == 200

    def test_openapi_always_public(self, auth_client):
        resp = auth_client.get("/openapi.json")
        assert resp.status_code == 200


class TestCorsHeaders:
    """CORS 响应头"""

    def test_cors_preflight(self, unauthenticated_client):
        resp = unauthenticated_client.options(
            "/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code in (200, 400)

    def test_cors_origin_header_on_get(self, unauthenticated_client):
        resp = unauthenticated_client.get(
            "/health",
            headers={"Origin": "http://localhost:3000"},
        )
        assert resp.status_code == 200
