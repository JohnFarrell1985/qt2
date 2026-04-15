"""E2E: 扩展数据查询链路 — 指数、财务、权重

覆盖 data_router 中此前未被测试的端点:
  GET /api/data/indices
  GET /api/data/index/{code}/daily
  GET /api/data/stock/{code}/financial/report
  GET /api/data/stock/{code}/financial/indicator
  GET /api/data/index/{code}/weight
"""


class TestIndexData:
    """指数数据 E2E"""

    def test_list_indices(self, client, seeded_db):
        """GET /api/data/indices — 返回 3 只合成指数"""
        resp = client.get("/api/data/indices")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) >= 3

        codes = {d["index_code"] for d in data}
        assert "000001.SH" in codes
        assert "000300.SH" in codes

        for item in data:
            assert item["data_points"] > 0

    def test_index_daily(self, client, seeded_db):
        """GET /api/data/index/000300.SH/daily — 沪深300 日线"""
        resp = client.get(
            "/api/data/index/000300.SH/daily",
            params={"start_date": "2024-06-01", "end_date": "2024-06-30", "limit": 100},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) > 0

        for item in data:
            assert item["index_code"] == "000300.SH"
            assert item["close"] > 0

    def test_index_daily_404(self, client, seeded_db):
        """不存在的指数代码 — 404"""
        resp = client.get("/api/data/index/999999.SH/daily")
        assert resp.status_code == 404

    def test_index_weight(self, client, seeded_db):
        """GET /api/data/index/000300.SH/weight — 沪深300 成分权重"""
        resp = client.get("/api/data/index/000300.SH/weight")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 30

        total_weight = sum(d["weight"] for d in data)
        assert abs(total_weight - 100.0) < 0.5, "权重合计应接近 100%"

    def test_index_weight_empty(self, client, seeded_db):
        """无权重数据的指数 — 返回空列表"""
        resp = client.get("/api/data/index/999999.SH/weight")
        assert resp.status_code == 200
        assert resp.json() == []


class TestFinancialData:
    """财务数据 E2E"""

    def test_financial_report(self, client, seeded_db):
        """GET /api/data/stock/000001.SZ/financial/report — 返回 4 期报表"""
        resp = client.get("/api/data/stock/000001.SZ/financial/report")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) == 4

        for item in data:
            assert item["code"] == "000001.SZ"
            assert item["total_assets"] > 0
            assert item["net_profit"] is not None

    def test_financial_report_empty(self, client, seeded_db):
        """不存在的股票 — 返回空列表"""
        resp = client.get("/api/data/stock/999999.SZ/financial/report")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_financial_indicator(self, client, seeded_db):
        """GET /api/data/stock/000005.SZ/financial/indicator — 财务指标"""
        resp = client.get("/api/data/stock/000005.SZ/financial/indicator")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) >= 1

        for item in data:
            assert item["code"] == "000005.SZ"
            assert item["eps_basic"] is not None

    def test_uptrend_stock_has_higher_roe(self, client, seeded_db):
        """上涨股 (1~10) 的 ROE 应高于下跌股 (11~20)"""
        resp1 = client.get("/api/data/stock/000001.SZ/financial/indicator")
        resp2 = client.get("/api/data/stock/000015.SZ/financial/indicator")
        assert resp1.status_code == 200
        assert resp2.status_code == 200

        roe_up = [d["roe_weighted"] for d in resp1.json() if d["roe_weighted"]]
        roe_down = [d["roe_weighted"] for d in resp2.json() if d["roe_weighted"]]

        if roe_up and roe_down:
            avg_up = sum(roe_up) / len(roe_up)
            avg_down = sum(roe_down) / len(roe_down)
            assert avg_up > avg_down, "上涨股 ROE 应大于下跌股"
