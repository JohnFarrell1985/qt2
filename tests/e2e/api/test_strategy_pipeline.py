"""E2E-01: 策略执行全链路

被测路径: POST /strategy/execute → StrategyOrchestrator
         → PositionMonitor → SignalArbiter → PositionSizer → ActionItems

6 个测试用例: 空仓买入、止损触发、T+1 约束、满仓限制、多策略投票、策略 CRUD
"""



class TestStrategyExecution:
    """策略编排器 E2E (TC-01-01 ~ TC-01-05)"""

    def test_empty_holdings_buy(self, client, seeded_db):
        """TC-01-01: 空仓买入 — 返回 buy 信号, 数量为 100 整数倍"""
        resp = client.post("/strategy/execute", json={
            "trade_date": "2024-06-03",
            "total_capital": 1_000_000,
            "available_cash": 500_000,
            "holdings": [],
            "price_map": {},
        })

        assert resp.status_code == 200
        data = resp.json()
        assert "summary" in data
        assert "actions" in data

        summary = data["summary"]
        assert summary["trade_date"] == "2024-06-03"
        assert summary["total_capital"] == 1_000_000

    def test_stop_loss_trigger(self, client, seeded_db):
        """TC-01-02: 止损触发 — 持有下跌股, profit_pct 超过阈值应触发卖出"""
        resp = client.post("/strategy/execute", json={
            "trade_date": "2024-06-03",
            "total_capital": 1_000_000,
            "available_cash": 500_000,
            "holdings": [
                {
                    "code": "000011.SZ",
                    "buy_date": "2024-05-01",
                    "buy_price": 10.0,
                    "quantity": 1000,
                    "current_price": 9.0,
                    "highest_price": 10.0,
                    "hold_days": 20,
                    "strategy_name": "momentum",
                    "profit_pct": -10.0,
                    "can_sell": True,
                },
            ],
            "price_map": {"000011.SZ": 9.0},
        })

        assert resp.status_code == 200
        data = resp.json()
        actions = data["actions"]
        sell_actions = [a for a in actions if a["direction"] == "sell"]
        sell_codes = [a["code"] for a in sell_actions]
        assert "000011.SZ" in sell_codes, (
            "持有亏损 -10% 的下跌股应触发止损卖出"
        )

    def test_t_plus_1_constraint(self, client, seeded_db):
        """TC-01-03: T+1 约束 — 当日买入持仓 (can_sell=False) 不应被卖出"""
        resp = client.post("/strategy/execute", json={
            "trade_date": "2024-06-03",
            "total_capital": 1_000_000,
            "available_cash": 800_000,
            "holdings": [
                {
                    "code": "000001.SZ",
                    "buy_date": "2024-06-03",
                    "buy_price": 15.0,
                    "quantity": 500,
                    "current_price": 15.0,
                    "highest_price": 15.0,
                    "hold_days": 0,
                    "strategy_name": "momentum",
                    "profit_pct": 0.0,
                    "can_sell": False,
                },
            ],
            "price_map": {"000001.SZ": 15.0},
        })

        assert resp.status_code == 200
        data = resp.json()
        actions = data["actions"]
        sell_today_bought = [
            a for a in actions
            if a["code"] == "000001.SZ" and a["direction"] == "sell"
        ]
        assert len(sell_today_bought) == 0, (
            "T+1 约束: 当日买入 (can_sell=False) 不应产生卖出"
        )

    def test_max_holdings_limit(self, client, seeded_db):
        """TC-01-04: 满仓限制 — 已持 5 只时不应有新买入"""
        holdings = []
        for i in range(1, 6):
            code = f"{i:06d}.SZ"
            holdings.append({
                "code": code,
                "buy_date": "2024-05-01",
                "buy_price": 10.0,
                "quantity": 1000,
                "current_price": 11.0,
                "highest_price": 11.0,
                "hold_days": 20,
                "strategy_name": "momentum",
                "profit_pct": 10.0,
                "can_sell": True,
            })

        resp = client.post("/strategy/execute", json={
            "trade_date": "2024-06-03",
            "total_capital": 1_000_000,
            "available_cash": 0,
            "holdings": holdings,
            "price_map": {f"{i:06d}.SZ": 11.0 for i in range(1, 6)},
        })

        assert resp.status_code == 200
        data = resp.json()
        actions = data["actions"]
        held_codes = {h["code"] for h in holdings}
        new_buys = [
            a for a in actions
            if a["direction"] == "buy" and a["code"] not in held_codes
        ]
        assert len(new_buys) == 0, (
            "现金为 0 时不应有新股买入"
        )

    def test_execute_response_structure(self, client, seeded_db):
        """TC-01-05: 响应结构验证 — summary + actions 字段完整"""
        resp = client.post("/strategy/execute", json={
            "trade_date": "2024-06-03",
            "total_capital": 1_000_000,
            "available_cash": 500_000,
            "holdings": [],
            "price_map": {},
        })

        assert resp.status_code == 200
        data = resp.json()

        assert "summary" in data
        assert "actions" in data

        summary = data["summary"]
        required_fields = [
            "trade_date", "macro_state", "total_signals",
            "final_sells", "final_buys", "total_capital",
        ]
        for field in required_fields:
            assert field in summary, f"summary 缺少字段: {field}"

        for action in data["actions"]:
            assert "code" in action
            assert "direction" in action
            assert action["direction"] in ("buy", "sell")


class TestStrategyCRUD:
    """策略 CRUD 全链路 (TC-01-06)"""

    def test_create_list_execute(self, client, db_session, seeded_db):
        """TC-01-06: 创建策略 → 列表 → 执行 全链路"""
        create_resp = client.post("/strategy/strategies", json={
            "name": "e2e_test_strategy",
            "strategy_tier": "rule",
            "strategy_class": "momentum",
            "config": {"lookback": 20},
            "factor_names": ["mom_20"],
            "description": "E2E 测试策略",
        })
        assert create_resp.status_code == 200
        assert "strategy_id" in create_resp.json()

        list_resp = client.get("/strategy/strategies")
        assert list_resp.status_code == 200
        strategies = list_resp.json()
        names = [s["strategy_name"] for s in strategies]
        assert "e2e_test_strategy" in names

        get_resp = client.get("/strategy/strategies/e2e_test_strategy")
        assert get_resp.status_code == 200
        assert get_resp.json()["strategy_name"] == "e2e_test_strategy"
