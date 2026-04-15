"""E2E-05: 系统健康与容错

被测路径: GET /health, 各端点错误处理, 并发安全

5 个测试用例: 健康检查(正常/异常)、无效 JSON、结构化错误、并发安全
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from unittest.mock import patch



class TestHealthCheck:
    """健康检查 E2E (TC-05-01 ~ TC-05-02)"""

    def test_health_ok(self, client, seeded_db):
        """TC-05-01: 健康检查 (正常) — DB 可达时返回 ok"""
        resp = client.get("/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["database"] == "connected"

    def test_health_db_down(self, client, seeded_db):
        """TC-05-02: 健康检查 (DB 异常) — 不返回 500, 返回 degraded"""
        with patch("src.api.main.check_db_connection", return_value=False):
            resp = client.get("/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["database"] == "unreachable"


class TestErrorHandling:
    """错误处理 E2E (TC-05-03 ~ TC-05-04)"""

    def test_invalid_json_returns_422(self, client, seeded_db):
        """TC-05-03: 无效 JSON — 返回 422 验证错误"""
        resp = client.post(
            "/strategy/execute",
            content=b"not valid json",
            headers={"content-type": "application/json"},
        )

        assert resp.status_code == 422
        data = resp.json()
        assert "detail" in data

    def test_wrong_type_returns_422(self, client, seeded_db):
        """TC-05-04: 错误类型 — total_capital 传字符串返回 422"""
        resp = client.post("/strategy/execute", json={
            "total_capital": "not_a_number",
        })

        assert resp.status_code == 422
        data = resp.json()
        assert "detail" in data

    def test_nonexistent_strategy_returns_404(self, client, seeded_db):
        """结构化错误 — 不存在的策略返回 404"""
        resp = client.get("/strategy/strategies/nonexistent_strategy_xyz")
        assert resp.status_code == 404

    def test_root_endpoint(self, client, seeded_db):
        """根路由返回系统信息"""
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert "name" in data
        assert "version" in data
        assert "modules" in data


class TestConcurrency:
    """并发安全 E2E (TC-05-05)"""

    def test_concurrent_execute(self, client, seeded_db):
        """TC-05-05: 并发安全 — 10 个并发 execute 请求全部成功"""
        def _make_request(i):
            return client.post("/strategy/execute", json={
                "trade_date": "2024-06-03",
                "total_capital": 1_000_000,
                "available_cash": 500_000,
                "holdings": [],
                "price_map": {},
            })

        results = []
        with ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(_make_request, i) for i in range(10)]
            for f in as_completed(futures):
                results.append(f.result())

        for resp in results:
            assert resp.status_code == 200, (
                f"并发请求失败: status={resp.status_code}"
            )

        assert len(results) == 10
