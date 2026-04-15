"""E2E: 策略池 / 标的池 / 宏观环境 / 分配扩展测试

覆盖 strategy_router 中此前未被充分测试的端点:
  GET /strategy/strategies (含 tier/status 过滤)
  GET /strategy/strategies/rank/{metric}
  GET /strategy/registry
  POST/GET /strategy/pools
  GET /strategy/macro/summary|states|history|mapping
  POST/GET/DELETE /strategy/allocations
  GET /strategy/plan
"""


class TestStrategyListFilter:
    """策略列表过滤 E2E"""

    def test_list_all_strategies(self, client, seeded_db):
        """策略列表 — 返回 ≥4 条（含种子数据的策略）"""
        resp = client.get("/strategy/strategies")
        assert resp.status_code == 200

        data = resp.json()
        names = [s["strategy_name"] for s in data]
        assert "momentum_v1" in names
        assert "lgb_multi_factor" in names

    def test_filter_by_tier(self, client, seeded_db):
        """按 tier=rule 过滤"""
        resp = client.get("/strategy/strategies", params={"tier": "rule"})
        assert resp.status_code == 200

        data = resp.json()
        for s in data:
            assert s["strategy_tier"] == "rule"

    def test_filter_by_status(self, client, seeded_db):
        """按 status=active 过滤"""
        resp = client.get("/strategy/strategies", params={"status": "active"})
        assert resp.status_code == 200

        data = resp.json()
        for s in data:
            assert s["status"] == "active"

    def test_rank_by_sharpe(self, client, seeded_db):
        """策略排名 — 按 backtest_sharpe 降序"""
        resp = client.get("/strategy/strategies/rank/backtest_sharpe")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) >= 1

        sharpes = [d.get("backtest_sharpe", 0) or 0 for d in data]
        for i in range(len(sharpes) - 1):
            assert sharpes[i] >= sharpes[i + 1], "排名应降序"

    def test_update_strategy_status(self, client, seeded_db):
        """暂停策略 → 确认状态变更"""
        resp = client.put(
            "/strategy/strategies/reversal_v1/status",
            params={"status": "archived"},
        )
        assert resp.status_code == 200

        check = client.get("/strategy/strategies/reversal_v1")
        assert check.status_code == 200
        assert check.json()["status"] == "archived"


class TestInstrumentPool:
    """标的池 E2E"""

    def test_list_pools(self, client, seeded_db):
        """标的池列表 — 返回 ≥3 个（含种子数据）"""
        resp = client.get("/strategy/pools")
        assert resp.status_code == 200

        data = resp.json()
        names = [p["pool_name"] for p in data]
        assert "全市场" in names
        assert "上涨池" in names

    def test_get_pool_detail(self, client, seeded_db):
        """标的池详情 — 含股票代码列表"""
        resp = client.get("/strategy/pools/全市场")
        assert resp.status_code == 200

        data = resp.json()
        assert data["pool_name"] == "全市场"
        assert data["n_stocks"] == 50

    def test_create_pool(self, client, seeded_db):
        """创建新标的池"""
        resp = client.post("/strategy/pools", json={
            "name": "e2e_test_pool",
            "codes": ["000001.SZ", "000002.SZ"],
            "description": "E2E 测试池",
        })
        assert resp.status_code == 200
        assert "pool_id" in resp.json()

        check = client.get("/strategy/pools/e2e_test_pool")
        assert check.status_code == 200
        assert check.json()["pool_name"] == "e2e_test_pool"

    def test_get_nonexistent_pool(self, client, seeded_db):
        """不存在的标的池 — 404"""
        resp = client.get("/strategy/pools/nonexistent_xyz")
        assert resp.status_code == 404


class TestMacroEnvironment:
    """宏观环境 E2E"""

    def test_macro_summary(self, client, seeded_db):
        """宏观摘要 — 返回当前状态信息"""
        resp = client.get("/strategy/macro/summary")
        assert resp.status_code == 200

        data = resp.json()
        assert "current_state" in data

    def test_macro_states(self, client, seeded_db):
        """可用宏观状态列表"""
        resp = client.get("/strategy/macro/states")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (list, dict))

    def test_macro_history(self, client, seeded_db):
        """宏观历史变更 — 返回 ≥3 条日志"""
        resp = client.get("/strategy/macro/history", params={"limit": 10})
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) >= 3

    def test_macro_mapping(self, client, seeded_db):
        """策略-宏观映射配置"""
        resp = client.get("/strategy/macro/mapping")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (list, dict))


class TestStrategyAllocation:
    """策略分配 E2E"""

    def test_list_allocations(self, client, seeded_db):
        """分配列表 — 返回 ≥3 条种子分配"""
        resp = client.get("/strategy/allocations")
        assert resp.status_code == 200

        data = resp.json()
        assert len(data) >= 3

    def test_create_allocation(self, client, seeded_db):
        """创建新分配"""
        resp = client.post("/strategy/allocations", json={
            "strategy_name": "momentum_v1",
            "pool_name": "低波红利池",
            "macro_state": "shock",
            "weight": 0.3,
        })
        assert resp.status_code == 200
        assert "allocation_id" in resp.json()

    def test_deactivate_allocation(self, client, seeded_db):
        create = client.post("/strategy/allocations", json={
            "strategy_name": "reversal_v1",
            "pool_name": "全市场",
            "macro_state": "bear",
            "weight": 0.2,
        })
        assert create.status_code == 200
        aid = create.json()["allocation_id"]

        resp = client.delete(f"/strategy/allocations/{aid}")
        assert resp.status_code == 200

    def test_current_plan(self, client, seeded_db):
        """获取当前宏观状态下的执行计划"""
        resp = client.get("/strategy/plan")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (list, dict))


class TestStrategyRegistry:
    """策略注册表 E2E"""

    def test_list_all_registered(self, client, seeded_db):
        """注册表 — 返回已注册策略列表"""
        resp = client.get("/strategy/registry")
        assert resp.status_code == 200
        assert isinstance(resp.json(), (list, dict))

    def test_list_by_tier(self, client, seeded_db):
        """按 tier 查询注册策略"""
        resp = client.get("/strategy/registry/rule")
        assert resp.status_code == 200
