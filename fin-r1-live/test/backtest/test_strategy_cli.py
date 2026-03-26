"""strategy_cli 单元测试"""
import json
import os
import sys
import tempfile
from datetime import date
from io import StringIO
from unittest.mock import patch, MagicMock

import pytest

from backtest.strategy_cli import (
    print_divider, print_strategy_result, print_trade_detail,
    print_skipped_detail, print_equity_curve,
    cmd_run, cmd_generate_mock, main,
)
from backtest.strategy_runner import StrategyResult, StrategyConfig, DayTrade


# ======== 辅助 ========

def _make_result(**overrides) -> StrategyResult:
    defaults = dict(
        config=StrategyConfig(),
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        initial_capital=1_000_000,
        final_capital=1_050_000,
        total_return=50_000,
        total_return_pct=5.0,
        annualized_return_pct=5.0,
        total_trades=10,
        win_trades=6,
        lose_trades=4,
        skipped_trades=2,
        win_rate=60.0,
        total_fees=500.0,
        max_single_profit=10000,
        max_single_loss=-5000,
        avg_profit_per_trade=5000,
        avg_holding_days=1.0,
        equity_curve=[
            {"date": "2025-01-02", "capital": 1000000},
            {"date": "2025-06-01", "capital": 1025000},
            {"date": "2025-12-31", "capital": 1050000},
        ],
        trades=[],
        skipped=[],
    )
    defaults.update(overrides)
    return StrategyResult(**defaults)


def _make_trade(**overrides) -> DayTrade:
    defaults = dict(
        code="000001", pick_date=date(2025, 1, 2),
        buy_date=date(2025, 1, 3), sell_date=date(2025, 1, 6),
        buy_price=10.2, sell_price=10.5, quantity=1000,
        buy_amount=10205.0, sell_amount=10490.0,
        fees=15.0, profit=285.0, profit_pct=2.79,
    )
    defaults.update(overrides)
    return DayTrade(**defaults)


# ======== 格式化输出 ========

class TestPrintDivider:
    def test_default(self, capsys):
        print_divider()
        out = capsys.readouterr().out
        assert "=" * 70 in out

    def test_custom(self, capsys):
        print_divider("-", 30)
        out = capsys.readouterr().out
        assert "-" * 30 in out


class TestPrintStrategyResult:
    def test_profit(self, capsys):
        r = _make_result()
        print_strategy_result(r)
        out = capsys.readouterr().out
        assert "T+1" in out
        assert "1,050,000" in out
        assert "5.00%" in out

    def test_loss(self, capsys):
        r = _make_result(total_return=-20000, total_return_pct=-2.0, annualized_return_pct=-2.0)
        print_strategy_result(r)
        out = capsys.readouterr().out
        assert "-2.00%" in out


class TestPrintTradeDetail:
    def test_empty(self, capsys):
        print_trade_detail([])
        out = capsys.readouterr().out
        assert "无交易" in out

    def test_with_trades(self, capsys):
        trades = [_make_trade(), _make_trade(code="000002", profit=-100, profit_pct=-0.98)]
        print_trade_detail(trades)
        out = capsys.readouterr().out
        assert "000001" in out
        assert "000002" in out

    def test_limit(self, capsys):
        trades = [_make_trade(code=f"00000{i}") for i in range(1, 6)]
        print_trade_detail(trades, limit=3)
        out = capsys.readouterr().out
        assert "最近 3" in out


class TestPrintSkippedDetail:
    def test_empty(self, capsys):
        print_skipped_detail([])
        out = capsys.readouterr().out
        assert out == ""

    def test_with_skipped(self, capsys):
        skipped = [DayTrade(
            code="000099", pick_date=date(2025, 1, 2), buy_date=date(2025, 1, 3),
            sell_date=date(2025, 1, 6), buy_price=22.0, sell_price=0,
            quantity=0, buy_amount=0, sell_amount=0, fees=0,
            profit=0, profit_pct=0, skipped=True, skip_reason="涨停开盘",
        )]
        print_skipped_detail(skipped)
        out = capsys.readouterr().out
        assert "涨停" in out


class TestPrintEquityCurve:
    def test_empty(self, capsys):
        print_equity_curve([])
        out = capsys.readouterr().out
        assert out == ""

    def test_with_data(self, capsys):
        curve = [
            {"date": f"2025-01-{i:02d}", "capital": 1000000 + i * 1000}
            for i in range(1, 25)
        ]
        print_equity_curve(curve, sample_interval=5)
        out = capsys.readouterr().out
        assert "净值曲线" in out


# ======== cmd_run ========

class TestCmdRun:
    def _make_schedule_file(self):
        data = {"2025-01-02": ["000001"]}
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, f)
        f.flush()
        f.close()
        return f.name

    def test_basic_run(self, capsys):
        path = self._make_schedule_file()
        try:
            args = MagicMock()
            args.schedule = path
            args.random_pool = None
            args.start = "2025-01-02"
            args.end = "2025-01-08"
            args.capital = 100_000
            args.max_position = 0.3
            args.max_holdings = 3
            args.limit_up = 9.8
            args.commission = None
            args.per_stock_amount = None
            args.continuous = False
            args.prompt = None
            args.prompt_file = None
            args.detail = False
            args.detail_limit = 50
            args.curve = False
            args.curve_interval = 20
            args.json = False
            args.output = None
            cmd_run(args)
            out = capsys.readouterr().out
            assert "策略" in out
        finally:
            os.unlink(path)

    def test_json_output(self, capsys):
        path = self._make_schedule_file()
        try:
            args = MagicMock()
            args.schedule = path
            args.random_pool = None
            args.start = "2025-01-02"
            args.end = "2025-01-08"
            args.capital = 100_000
            args.max_position = 0.3
            args.max_holdings = 3
            args.limit_up = 9.8
            args.commission = None
            args.per_stock_amount = None
            args.continuous = False
            args.prompt = None
            args.prompt_file = None
            args.detail = True
            args.detail_limit = 50
            args.curve = True
            args.curve_interval = 20
            args.json = True
            args.output = None
            cmd_run(args)
            out = capsys.readouterr().out
            # Should contain JSON and formatted output
            assert "T+1" in out
        finally:
            os.unlink(path)

    def test_json_to_file(self, capsys):
        sched_path = self._make_schedule_file()
        out_path = tempfile.mktemp(suffix=".json")
        try:
            args = MagicMock()
            args.schedule = sched_path
            args.random_pool = None
            args.start = "2025-01-02"
            args.end = "2025-01-08"
            args.capital = 100_000
            args.max_position = 0.3
            args.max_holdings = 3
            args.limit_up = 9.8
            args.commission = None
            args.per_stock_amount = None
            args.continuous = False
            args.prompt = None
            args.prompt_file = None
            args.detail = True
            args.detail_limit = 50
            args.curve = False
            args.curve_interval = 20
            args.json = True
            args.output = out_path
            cmd_run(args)
            assert os.path.exists(out_path)
            with open(out_path, encoding="utf-8") as f:
                data = json.load(f)
            assert "total_trades" in data
        finally:
            os.unlink(sched_path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_random_pool(self, capsys):
        args = MagicMock()
        args.schedule = None
        args.random_pool = "000001,000002"
        args.random_count = 1
        args.seed = 42
        args.start = "2025-01-02"
        args.end = "2025-01-08"
        args.capital = 100_000
        args.max_position = 0.3
        args.max_holdings = 3
        args.limit_up = 9.8
        args.commission = None
        args.per_stock_amount = None
        args.continuous = False
        args.prompt = None
        args.prompt_file = None
        args.detail = False
        args.detail_limit = 50
        args.curve = False
        args.curve_interval = 20
        args.json = False
        args.output = None
        cmd_run(args)
        out = capsys.readouterr().out
        assert "T+1" in out

    def test_no_picker_exits(self):
        args = MagicMock()
        args.schedule = None
        args.random_pool = None
        args.start = "2025-01-02"
        args.end = "2025-01-08"
        args.capital = 100_000
        args.max_position = 0.3
        args.max_holdings = 3
        args.limit_up = 9.8
        args.commission = None
        args.per_stock_amount = None
        with pytest.raises(SystemExit):
            cmd_run(args)

    def test_with_prompt_file(self, capsys):
        sched_path = self._make_schedule_file()
        prompt_path = tempfile.mktemp(suffix=".txt")
        with open(prompt_path, "w", encoding="utf-8") as f:
            f.write("测试提示词")
        try:
            args = MagicMock()
            args.schedule = sched_path
            args.random_pool = None
            args.start = "2025-01-02"
            args.end = "2025-01-08"
            args.capital = 100_000
            args.max_position = 0.3
            args.max_holdings = 3
            args.limit_up = 9.8
            args.commission = None
            args.per_stock_amount = None
            args.continuous = False
            args.prompt = None
            args.prompt_file = prompt_path
            args.detail = False
            args.detail_limit = 50
            args.curve = False
            args.curve_interval = 20
            args.json = False
            args.output = None
            cmd_run(args)
        finally:
            os.unlink(sched_path)
            os.unlink(prompt_path)

    def test_custom_commission(self, capsys):
        path = self._make_schedule_file()
        try:
            args = MagicMock()
            args.schedule = path
            args.random_pool = None
            args.start = "2025-01-02"
            args.end = "2025-01-08"
            args.capital = 100_000
            args.max_position = 0.3
            args.max_holdings = 3
            args.limit_up = 9.8
            args.commission = 0.0001
            args.per_stock_amount = None
            args.continuous = False
            args.prompt = None
            args.prompt_file = None
            args.detail = True
            args.detail_limit = 50
            args.curve = False
            args.curve_interval = 20
            args.json = False
            args.output = None
            cmd_run(args)
        finally:
            os.unlink(path)

    def test_continuous_mode(self, capsys):
        data = {
            "2025-01-02": ["000001"],
            "2025-01-03": ["000001"],
            "2025-01-06": ["000002"],
        }
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, f)
        f.flush()
        f.close()
        try:
            args = MagicMock()
            args.schedule = f.name
            args.random_pool = None
            args.start = "2025-01-02"
            args.end = "2025-01-08"
            args.capital = 100_000
            args.max_position = 0.3
            args.max_holdings = 3
            args.limit_up = 9.8
            args.commission = None
            args.per_stock_amount = None
            args.continuous = True
            args.prompt = None
            args.prompt_file = None
            args.detail = True
            args.detail_limit = 50
            args.curve = True
            args.curve_interval = 5
            args.json = False
            args.output = None
            cmd_run(args)
            out = capsys.readouterr().out
            assert "策略" in out
        finally:
            os.unlink(f.name)

    def test_continuous_with_prompt_template(self, capsys):
        data = {
            "2025-01-02": ["000001"],
            "2025-01-03": ["000001"],
        }
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, f)
        f.flush()
        f.close()
        try:
            args = MagicMock()
            args.schedule = f.name
            args.random_pool = None
            args.start = "2025-01-02"
            args.end = "2025-01-08"
            args.capital = 100_000
            args.max_position = 0.3
            args.max_holdings = 3
            args.limit_up = 9.8
            args.commission = None
            args.per_stock_amount = None
            args.continuous = True
            args.prompt = "prompt1.txt"
            args.prompt_file = None
            args.detail = False
            args.detail_limit = 50
            args.curve = False
            args.curve_interval = 20
            args.json = False
            args.output = None
            cmd_run(args)
            out = capsys.readouterr().out
            assert "策略" in out
        finally:
            os.unlink(f.name)


# ======== cmd_generate_mock ========

class TestCmdGenerateMock:
    def test_generate(self, capsys):
        out_path = tempfile.mktemp(suffix=".json")
        try:
            args = MagicMock()
            args.pool = "000001,000002,600519"
            args.interval = 2
            args.count = 1
            args.start = "2025-01-02"
            args.end = "2025-01-08"
            args.seed = 42
            args.output = out_path
            cmd_generate_mock(args)
            assert os.path.exists(out_path)
            with open(out_path, encoding="utf-8") as f:
                data = json.load(f)
            assert len(data) > 0
        finally:
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_no_trading_dates_exits(self):
        args = MagicMock()
        args.pool = "000001"
        args.interval = 1
        args.count = 1
        args.start = "2020-01-01"
        args.end = "2020-01-05"
        args.seed = 42
        args.output = None
        with pytest.raises(SystemExit):
            cmd_generate_mock(args)

    def test_default_output(self, capsys, tmp_path):
        args = MagicMock()
        args.pool = "000001"
        args.interval = 1
        args.count = 1
        args.start = "2025-01-02"
        args.end = "2025-01-08"
        args.seed = 42
        args.output = None
        # Will write to current dir's mock_schedule.json
        old_cwd = os.getcwd()
        os.chdir(str(tmp_path))
        try:
            cmd_generate_mock(args)
            assert os.path.exists("mock_schedule.json")
        finally:
            os.chdir(old_cwd)


# ======== main ========

class TestMain:
    def test_no_command_shows_help(self, capsys):
        with patch("sys.argv", ["strategy_cli"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0

    def test_run_subcommand(self, capsys):
        data = {"2025-01-02": ["000001"]}
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, f)
        f.flush()
        f.close()
        try:
            with patch("sys.argv", [
                "strategy_cli", "run",
                "--schedule", f.name,
                "--start", "2025-01-02",
                "--end", "2025-01-08",
                "--capital", "100000",
            ]):
                main()
            out = capsys.readouterr().out
            assert "T+1" in out
        finally:
            os.unlink(f.name)

    def test_verbose_flag(self, capsys):
        data = {"2025-01-02": ["000001"]}
        f = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8")
        json.dump(data, f)
        f.flush()
        f.close()
        try:
            with patch("sys.argv", [
                "strategy_cli", "-v", "run",
                "--schedule", f.name,
                "--start", "2025-01-02",
                "--end", "2025-01-08",
            ]):
                main()
        finally:
            os.unlink(f.name)
