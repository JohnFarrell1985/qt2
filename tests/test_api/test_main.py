"""Tests for src/api/main.py

Uses FastAPI TestClient for synchronous endpoint testing.
Patches lifespan dependencies (DB init, scheduler) to avoid side effects.
"""
import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def patch_lifespan():
    """Prevent actual DB init and scheduler from running during tests."""
    with patch("src.api.main.init_database"), \
         patch("src.api.main.start_scheduler"), \
         patch("src.api.main.stop_scheduler"):
        yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from src.api.main import app
    with TestClient(app) as c:
        yield c


class TestRootEndpoint:

    def test_returns_system_info(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "A股量化因子迭代平台"
        assert data["version"] == "3.0.0"
        assert "docs" in data
        assert isinstance(data["modules"], list)
        assert "data" in data["modules"]
        assert "trading" in data["modules"]


class TestHealthEndpoint:

    @patch("src.api.main.check_db_connection", return_value=True)
    def test_returns_ok_when_db_up(self, mock_db, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"

    @patch("src.api.main.check_db_connection", return_value=False)
    def test_returns_degraded_when_db_down(self, mock_db, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["database"] == "unreachable"
