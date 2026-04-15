"""E2E: 情绪引擎 API 测试

覆盖 sentiment_router:
  GET /api/sentiment/latest
  GET /api/sentiment/date/{date}
  GET /api/sentiment/history
  POST /api/sentiment/ingest
  GET /api/sentiment/ingest-log
  GET /api/sentiment/profiles*
"""


class TestSentimentQuery:
    """情绪数据查询 E2E"""

    def test_latest_sentiment(self, client, seeded_db):
        """GET /api/sentiment/latest — 返回最近一日情绪"""
        resp = client.get("/api/sentiment/latest")
        assert resp.status_code == 200

        data = resp.json()
        assert "trade_date" in data
        assert "composite_sentiment" in data
        assert data["composite_sentiment"] is not None
        assert -1.0 <= data["composite_sentiment"] <= 1.0

    def test_sentiment_by_date(self, client, seeded_db):
        """GET /api/sentiment/date/2024-06-03 — 指定日期"""
        resp = client.get("/api/sentiment/date/2024-06-03")
        assert resp.status_code == 200

        data = resp.json()
        assert data["trade_date"] == "2024-06-03"
        assert "ad_ratio" in data
        assert "suggested_state" in data

    def test_sentiment_date_404(self, client, seeded_db):
        """不存在的日期 — 404"""
        resp = client.get("/api/sentiment/date/2020-01-01")
        assert resp.status_code == 404

    def test_sentiment_history(self, client, seeded_db):
        """GET /api/sentiment/history — 返回多条记录"""
        resp = client.get(
            "/api/sentiment/history",
            params={"start_date": "2024-06-01", "end_date": "2024-06-30", "limit": 30},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) >= 10

        for item in data:
            assert "trade_date" in item
            assert "composite_sentiment" in item

    def test_sentiment_has_sub_indices(self, client, seeded_db):
        """情绪数据应包含各子指标"""
        resp = client.get("/api/sentiment/latest")
        data = resp.json()

        for field in ["earning_effect", "capital_mood", "volatility_mood",
                       "sector_heat", "news_mood", "global_mood"]:
            assert field in data, f"缺少情绪子指标: {field}"


class TestSentimentIngest:
    """情绪采集 E2E"""

    def test_ingest_with_data(self, client, seeded_db):
        """POST /api/sentiment/ingest — 使用合成行情计算量价情绪"""
        resp = client.post(
            "/api/sentiment/ingest",
            params={"trade_date": "2024-06-03"},
        )

        if resp.status_code == 200:
            data = resp.json()
            assert data["status"] == "success"
            assert "indicators" in data
        else:
            assert resp.status_code == 404

    def test_ingest_log(self, client, seeded_db):
        """GET /api/sentiment/ingest-log — 返回采集日志"""
        resp = client.get("/api/sentiment/ingest-log", params={"limit": 10})
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) >= 2

        for item in data:
            assert "trade_date" in item
            assert "source_name" in item
            assert "status" in item

    def test_ingest_log_filter_by_date(self, client, seeded_db):
        """按日期筛选采集日志"""
        resp = client.get(
            "/api/sentiment/ingest-log",
            params={"trade_date": "2024-06-03"},
        )
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) >= 1
        for item in data:
            assert item["trade_date"] == "2024-06-03"


class TestSentimentProfiles:
    """情绪策略参数 Profile E2E"""

    def test_get_profiles(self, client, seeded_db):
        """GET /api/sentiment/profiles — 返回配置"""
        resp = client.get("/api/sentiment/profiles")
        assert resp.status_code == 200

    def test_reload_profiles(self, client, seeded_db):
        """POST /api/sentiment/profiles/reload — 热更新"""
        resp = client.post("/api/sentiment/profiles/reload")
        assert resp.status_code == 200
        assert resp.json()["status"] == "reloaded"
