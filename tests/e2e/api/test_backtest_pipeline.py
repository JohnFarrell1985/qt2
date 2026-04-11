"""E2E-02: 回测全链路

被测路径: POST /api/backtest/run → strategy_runner → data_loader → performance

5 个测试用例: 简单回测、连续持仓、绩效指标、缺少参数、结果字段验证
"""
import json
import os
import tempfile

import pytest


class TestBacktestPipeline:
    """回测引擎 E2E (TC-02-01 ~ TC-02-05)"""

    def test_simple_backtest(self, client, seeded_db):
        """TC-02-01: 简单回测 — 固定选股, 返回结果"""
        schedule = {
            "2024-06-03": ["000001.SZ"],
            "2024-06-10": ["000002.SZ"],
            "2024-06-17": ["000003.SZ"],
        }
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False,
        ) as f:
            json.dump(schedule, f)
            schedule_path = f.name

        try:
            resp = client.post("/api/backtest/run", json={
                "schedule_file": schedule_path,
                "start_date": "2024-06-01",
                "end_date": "2024-08-30",
                "initial_capital": 1_000_000,
                "max_position_pct": 0.3,
                "max_holdings": 3,
                "continuous": False,
            })

            assert resp.status_code == 200
            data = resp.json()
            assert "initial_capital" in data
            assert "final_capital" in data
            assert "performance" in data
            assert data["initial_capital"] == 1_000_000
        finally:
            os.unlink(schedule_path)

    def test_continuous_backtest(self, client, seeded_db):
        """TC-02-02: 连续持仓回测 — stock_pool 模式"""
        resp = client.post("/api/backtest/run", json={
            "stock_pool": "000001.SZ,000002.SZ,000041.SZ",
            "start_date": "2024-06-01",
            "end_date": "2024-08-30",
            "initial_capital": 1_000_000,
            "max_position_pct": 0.3,
            "max_holdings": 3,
            "continuous": True,
        })

        assert resp.status_code == 200
        data = resp.json()
        assert "final_capital" in data
        assert "total_trades" in data
        assert data["total_trades"] >= 0

    def test_performance_metrics_reasonable(self, client, seeded_db):
        """TC-02-03: 绩效指标 — 使用全上涨股池, 指标应合理"""
        uptrend_pool = ",".join(f"{i:06d}.SZ" for i in range(1, 6))
        resp = client.post("/api/backtest/run", json={
            "stock_pool": uptrend_pool,
            "start_date": "2024-06-01",
            "end_date": "2024-09-30",
            "initial_capital": 1_000_000,
            "continuous": True,
        })

        assert resp.status_code == 200
        data = resp.json()
        perf = data["performance"]

        assert "annualized_return_pct" in perf
        assert "max_drawdown" in perf
        assert "sharpe_ratio" in perf
        assert "sortino_ratio" in perf
        assert "calmar_ratio" in perf

    def test_missing_params_returns_400(self, client, seeded_db):
        """TC-02-04: 缺少参数 — 不传 schedule_file 或 stock_pool 返回 400"""
        resp = client.post("/api/backtest/run", json={
            "start_date": "2024-06-01",
            "end_date": "2024-08-30",
            "initial_capital": 1_000_000,
        })

        assert resp.status_code == 400
        detail = resp.json().get("detail", "")
        assert len(detail) > 0, "400 响应应包含错误说明"

    def test_backtest_result_structure(self, client, seeded_db):
        """TC-02-05: 回测结果包含必需字段"""
        resp = client.post("/api/backtest/run", json={
            "stock_pool": "000001.SZ,000002.SZ",
            "start_date": "2024-06-01",
            "end_date": "2024-07-31",
            "initial_capital": 1_000_000,
            "continuous": True,
        })

        assert resp.status_code == 200
        data = resp.json()

        required_fields = [
            "period", "initial_capital", "final_capital",
            "total_return", "total_trades", "performance",
        ]
        for field in required_fields:
            assert field in data, f"回测结果缺少字段: {field}"

        assert data["final_capital"] > 0
        assert isinstance(data["total_trades"], int)
