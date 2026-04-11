"""E2E-04: 数据查询链路

被测路径: GET /api/data/* 和 GET /api/factor/* 系列端点

4 个测试用例: 股票列表、日线行情、因子列表、数据一致性
"""
import pytest


class TestDataQuery:
    """数据查询 E2E (TC-04-01 ~ TC-04-04)"""

    def test_stock_list(self, client, seeded_db):
        """TC-04-01: 股票列表 — 返回 50 只合成股票"""
        resp = client.get("/api/data/stocks", params={"limit": 100})

        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "items" in data
        assert data["total"] == 50

        for item in data["items"]:
            assert "code" in item
            assert "name" in item

    def test_stock_daily(self, client, seeded_db):
        """TC-04-02: 日线行情 — 查询特定股票特定日期范围"""
        resp = client.get(
            "/api/data/stock/000001.SZ/daily",
            params={
                "start_date": "2024-06-01",
                "end_date": "2024-06-30",
                "limit": 100,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) > 0

        for item in data:
            assert "code" in item
            assert item["code"] == "000001.SZ"
            assert "trade_date" in item
            assert "open" in item
            assert "high" in item
            assert "low" in item
            assert "close" in item
            assert item["close"] > 0

    def test_factor_list(self, client, seeded_db):
        """TC-04-03: 因子列表 — 返回 5 个合成因子"""
        resp = client.get("/api/factor/list")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 5

        factor_names = [f.get("factor_name") or f.get("name", "") for f in data]
        for expected in ["mom_20", "vol_20", "rsi_14"]:
            assert expected in factor_names, f"因子列表缺少 {expected}"

    def test_stock_info(self, client, seeded_db):
        """TC-04-04: 股票详情 — 查询单只股票信息"""
        resp = client.get("/api/data/stock/000001.SZ/info")

        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == "000001.SZ"
        assert "name" in data
        assert "exchange" in data


class TestDataPagination:
    """分页参数验证"""

    def test_stock_list_pagination(self, client, seeded_db):
        """分页参数 limit/offset 正确生效"""
        resp1 = client.get("/api/data/stocks", params={"limit": 10, "offset": 0})
        resp2 = client.get("/api/data/stocks", params={"limit": 10, "offset": 10})

        assert resp1.status_code == 200
        assert resp2.status_code == 200

        items1 = resp1.json()["items"]
        items2 = resp2.json()["items"]

        assert len(items1) == 10
        assert len(items2) == 10

        codes1 = {i["code"] for i in items1}
        codes2 = {i["code"] for i in items2}
        assert codes1.isdisjoint(codes2), "分页后两页数据不应重叠"

    def test_daily_limit(self, client, seeded_db):
        """日线查询 limit 参数"""
        resp = client.get(
            "/api/data/stock/000001.SZ/daily",
            params={"limit": 5},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) <= 5
