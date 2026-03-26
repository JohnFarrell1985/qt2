"""
cli.py 单元测试 — 子命令/格式化输出/交互模式全覆盖
"""
import json
import os
import sys
import tempfile
from datetime import date
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest

from backtest.cli import (
    main, cmd_trade, cmd_portfolio, cmd_interactive, cmd_info,
    print_divider, print_trade_result, print_portfolio_summary,
)
from backtest.engine import TradeResult, PortfolioSummary, calc_single_trade
from backtest.fees import TradeFees, detect_market


# ======== Helpers ========

def _make_trade_result(code="000001", profit=100.0, **kw):
    defaults = dict(
        code=code, name="平安银行",
        buy_date=date(2025, 1, 2), buy_price=10.2, buy_quantity=1000,
        buy_amount=10205.0, buy_fees=TradeFees(commission=5.0),
        sell_date=date(2025, 1, 8), sell_price=10.5, sell_quantity=1000,
        sell_amount=10305.0, sell_fees=TradeFees(commission=5.0, stamp_tax=10.5),
        total_fees=20.5, net_profit=profit, profit_pct=round(profit / 10205 * 100, 2),
        holding_days=6,
    )
    defaults.update(kw)
    return TradeResult(**defaults)


def _make_hk_result():
    return _make_trade_result(
        code="00700", name="腾讯控股",
        buy_price=385.0, sell_price=398.0,
        buy_fees=TradeFees(commission=23.1, stamp_tax=77.0, transfer_fee=2.52),
        sell_fees=TradeFees(commission=23.88, stamp_tax=80.0, transfer_fee=2.6),
    )


# ======== print_divider ========

class TestPrintDivider:
    def test_default(self, capsys):
        print_divider()
        out = capsys.readouterr().out
        assert "=" * 60 in out

    def test_custom(self, capsys):
        print_divider("-", 30)
        out = capsys.readouterr().out
        assert "-" * 30 in out


# ======== print_trade_result ========

class TestPrintTradeResult:
    def test_a_share_output(self, capsys):
        r = _make_trade_result()
        print_trade_result(r)
        out = capsys.readouterr().out
        assert "000001" in out
        assert "平安银行" in out
        assert "[A股]" in out
        assert "买入" in out
        assert "卖出" in out
        assert "费用" in out
        assert "盈亏" in out
        assert "元" in out

    def test_hk_output(self, capsys):
        r = _make_hk_result()
        print_trade_result(r)
        out = capsys.readouterr().out
        assert "00700" in out
        assert "腾讯控股" in out
        assert "[港股通]" in out
        assert "港元" in out
        assert "买入印花税" in out
        assert "卖出印花税" in out

    def test_profit_positive_color(self, capsys):
        r = _make_trade_result(profit=500.0)
        print_trade_result(r)
        out = capsys.readouterr().out
        assert "\033[32m" in out  # green

    def test_profit_negative_color(self, capsys):
        r = _make_trade_result(profit=-300.0)
        print_trade_result(r)
        out = capsys.readouterr().out
        assert "\033[31m" in out  # red

    def test_period_high_low(self, capsys):
        r = _make_trade_result(period_high=11.0, period_low=9.8, max_drawdown_pct=4.5)
        print_trade_result(r)
        out = capsys.readouterr().out
        assert "11.00" in out
        assert "9.80" in out
        assert "4.50%" in out

    def test_no_period_data(self, capsys):
        r = _make_trade_result()
        print_trade_result(r)
        out = capsys.readouterr().out
        assert "区间最高" not in out

    def test_a_share_sh_transfer_fee(self, capsys):
        """沪市有过户费"""
        r = _make_trade_result(
            code="600519", name="贵州茅台",
            buy_fees=TradeFees(commission=5.0, transfer_fee=0.3),
            sell_fees=TradeFees(commission=5.0, stamp_tax=10.0, transfer_fee=0.3),
        )
        print_trade_result(r)
        out = capsys.readouterr().out
        assert "过户费" in out

    def test_hk_misc_fee_label(self, capsys):
        r = _make_hk_result()
        print_trade_result(r)
        out = capsys.readouterr().out
        assert "杂费" in out
        assert "交易费+征费+交收费" in out

    def test_a_share_no_buy_transfer_fee(self, capsys):
        """深市无过户费，不显示"""
        r = _make_trade_result(code="000001")
        print_trade_result(r)
        out = capsys.readouterr().out
        assert "过户费" not in out

    def test_name_none(self, capsys):
        r = _make_trade_result(name=None)
        print_trade_result(r)
        out = capsys.readouterr().out
        assert "000001" in out


# ======== print_portfolio_summary ========

class TestPrintPortfolioSummary:
    def _make_summary(self, **kw):
        defaults = dict(
            start_date=date(2025, 1, 1), end_date=date(2025, 6, 30),
            total_trades=3, win_trades=2, lose_trades=1, win_rate=66.7,
            total_invested=30000, total_returned=31500, total_fees=60,
            net_profit=1500, profit_pct=5.0,
            max_single_profit=1000, max_single_loss=-200,
            avg_profit_per_trade=500, avg_holding_days=25.3,
        )
        defaults.update(kw)
        return PortfolioSummary(**defaults)

    def test_output_contains_key_fields(self, capsys):
        s = self._make_summary()
        print_portfolio_summary(s)
        out = capsys.readouterr().out
        assert "汇总统计" in out
        assert "2025-01-01" in out
        assert "2025-06-30" in out
        assert "66.7%" in out
        assert "5.00%" in out

    def test_negative_profit(self, capsys):
        s = self._make_summary(net_profit=-500, profit_pct=-1.67)
        print_portfolio_summary(s)
        out = capsys.readouterr().out
        assert "\033[31m" in out  # red

    def test_positive_profit(self, capsys):
        s = self._make_summary()
        print_portfolio_summary(s)
        out = capsys.readouterr().out
        assert "\033[32m" in out  # green


# ======== cmd_trade ========

class TestCmdTrade:
    def test_trade_by_qty(self, capsys):
        args = SimpleNamespace(
            code="000001", buy="2025-01-02", sell="2025-01-08",
            qty=1000, amount=None, commission=None, stamp_tax=None, json=False,
        )
        cmd_trade(args)
        out = capsys.readouterr().out
        assert "000001" in out
        assert "平安银行" in out

    def test_trade_by_amount(self, capsys):
        args = SimpleNamespace(
            code="000001", buy="2025-01-02", sell="2025-01-08",
            qty=None, amount=50000.0, commission=None, stamp_tax=None, json=False,
        )
        cmd_trade(args)
        out = capsys.readouterr().out
        assert "000001" in out

    def test_trade_json_output(self, capsys):
        args = SimpleNamespace(
            code="000001", buy="2025-01-02", sell="2025-01-08",
            qty=1000, amount=None, commission=None, stamp_tax=None, json=True,
        )
        cmd_trade(args)
        out = capsys.readouterr().out
        assert '"code": "000001"' in out

    def test_trade_custom_commission(self, capsys):
        args = SimpleNamespace(
            code="000001", buy="2025-01-02", sell="2025-01-08",
            qty=1000, amount=None, commission=0.001, stamp_tax=None, json=False,
        )
        cmd_trade(args)
        # Should not raise
        out = capsys.readouterr().out
        assert "000001" in out

    def test_trade_custom_stamp_tax(self, capsys):
        args = SimpleNamespace(
            code="000001", buy="2025-01-02", sell="2025-01-08",
            qty=1000, amount=None, commission=None, stamp_tax=0.0005, json=False,
        )
        cmd_trade(args)
        out = capsys.readouterr().out
        assert "000001" in out

    def test_trade_error_exits(self):
        args = SimpleNamespace(
            code="000001", buy="2025-01-08", sell="2025-01-02",
            qty=1000, amount=None, commission=None, stamp_tax=None, json=False,
        )
        with pytest.raises(SystemExit):
            cmd_trade(args)


# ======== cmd_portfolio ========

class TestCmdPortfolio:
    def test_portfolio_from_file(self, capsys, tmp_path):
        trades = [
            {"code": "000001", "buy_date": "2025-01-02", "sell_date": "2025-01-08", "quantity": 1000},
            {"code": "600519", "buy_date": "2025-02-05", "sell_date": "2025-02-06", "quantity": 100},
        ]
        f = tmp_path / "trades.json"
        f.write_text(json.dumps(trades), encoding="utf-8")

        args = SimpleNamespace(file=str(f), json=False)
        cmd_portfolio(args)
        out = capsys.readouterr().out
        assert "000001" in out
        assert "600519" in out
        assert "汇总统计" in out

    def test_portfolio_with_json(self, capsys, tmp_path):
        trades = [
            {"code": "000001", "buy_date": "2025-01-02", "sell_date": "2025-01-08", "quantity": 1000},
        ]
        f = tmp_path / "trades.json"
        f.write_text(json.dumps(trades), encoding="utf-8")

        args = SimpleNamespace(file=str(f), json=True)
        cmd_portfolio(args)
        out = capsys.readouterr().out
        assert '"total_trades"' in out

    def test_portfolio_skips_bad_trade(self, capsys, tmp_path):
        trades = [
            {"code": "000001", "buy_date": "2025-01-08", "sell_date": "2025-01-02", "quantity": 1000},
            {"code": "000001", "buy_date": "2025-01-02", "sell_date": "2025-01-08", "quantity": 1000},
        ]
        f = tmp_path / "trades.json"
        f.write_text(json.dumps(trades), encoding="utf-8")

        args = SimpleNamespace(file=str(f), json=False)
        cmd_portfolio(args)
        captured = capsys.readouterr()
        assert "SKIP" in captured.err
        assert "汇总统计" in captured.out

    def test_portfolio_all_fail(self, capsys, tmp_path):
        trades = [
            {"code": "000001", "buy_date": "2025-01-08", "sell_date": "2025-01-02", "quantity": 1000},
        ]
        f = tmp_path / "trades.json"
        f.write_text(json.dumps(trades), encoding="utf-8")

        args = SimpleNamespace(file=str(f), json=False)
        cmd_portfolio(args)
        out = capsys.readouterr().out
        assert "没有有效的交易记录" in out

    def test_portfolio_by_amount(self, capsys, tmp_path):
        trades = [
            {"code": "000001", "buy_date": "2025-01-02", "sell_date": "2025-01-08", "amount": 50000.0},
        ]
        f = tmp_path / "trades.json"
        f.write_text(json.dumps(trades), encoding="utf-8")

        args = SimpleNamespace(file=str(f), json=False)
        cmd_portfolio(args)
        out = capsys.readouterr().out
        assert "000001" in out


# ======== cmd_info ========

class TestCmdInfo:
    def test_known_stock(self, capsys):
        args = SimpleNamespace(code="000001")
        cmd_info(args)
        out = capsys.readouterr().out
        assert "000001" in out
        assert "平安银行" in out
        assert "2024-01-02" in out
        assert "480" in out

    def test_unknown_stock(self, capsys):
        args = SimpleNamespace(code="999999")
        cmd_info(args)
        out = capsys.readouterr().out
        assert "999999" in out
        assert "未知" in out
        assert "无记录" in out


# ======== cmd_interactive ========

class TestCmdInteractive:
    def test_quit_immediately(self, capsys):
        with patch("builtins.input", side_effect=["q"]):
            cmd_interactive(SimpleNamespace())

    def test_summary_no_trades(self, capsys):
        with patch("builtins.input", side_effect=["s", "q"]):
            cmd_interactive(SimpleNamespace())
        out = capsys.readouterr().out
        assert "暂无交易记录" in out

    def test_one_trade_then_quit(self, capsys):
        inputs = [
            "000001",          # code
            "2025-01-02",      # buy date
            "2025-01-08",      # sell date
            "q",               # mode: q=quantity
            "1000",            # quantity
            "q",               # quit
            "n",               # no summary
        ]
        with patch("builtins.input", side_effect=inputs):
            cmd_interactive(SimpleNamespace())
        out = capsys.readouterr().out
        assert "000001" in out

    def test_one_trade_by_amount(self, capsys):
        inputs = [
            "000001",
            "2025-01-02",
            "2025-01-08",
            "a",               # mode: a=amount
            "50000",           # amount
            "q",               # quit
            "y",               # view summary
        ]
        with patch("builtins.input", side_effect=inputs):
            cmd_interactive(SimpleNamespace())
        out = capsys.readouterr().out
        assert "000001" in out
        assert "汇总统计" in out

    def test_keyboard_interrupt(self, capsys):
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            cmd_interactive(SimpleNamespace())

    def test_eof_error(self, capsys):
        with patch("builtins.input", side_effect=EOFError):
            cmd_interactive(SimpleNamespace())

    def test_value_error_continues(self, capsys):
        inputs = [
            "000001",
            "2025-01-08",      # buy
            "2025-01-02",      # sell (invalid: before buy)
            "q",               # mode
            "1000",            # qty
            "q",               # quit
        ]
        with patch("builtins.input", side_effect=inputs):
            cmd_interactive(SimpleNamespace())
        out = capsys.readouterr().out
        assert "ERROR" in out

    def test_summary_with_eof_on_confirm(self, capsys):
        inputs = [
            "000001",
            "2025-01-02",
            "2025-01-08",
            "q",
            "1000",
            "q",
        ]
        with patch("builtins.input", side_effect=inputs + [EOFError]):
            cmd_interactive(SimpleNamespace())

    def test_view_summary_mid_session(self, capsys):
        inputs = [
            "000001",          # trade 1
            "2025-01-02",
            "2025-01-08",
            "q",
            "1000",
            "s",               # view summary
            "q",               # quit
            "n",               # no final summary
        ]
        with patch("builtins.input", side_effect=inputs):
            cmd_interactive(SimpleNamespace())
        out = capsys.readouterr().out
        assert "汇总统计" in out

    def test_stock_name_displayed(self, capsys):
        inputs = [
            "000001",          # known stock
            "2025-01-02",
            "2025-01-08",
            "q",
            "1000",
            "q",               # quit
            "n",
        ]
        with patch("builtins.input", side_effect=inputs):
            cmd_interactive(SimpleNamespace())
        out = capsys.readouterr().out
        assert "平安银行" in out


# ======== main() ========

class TestMain:
    def test_no_args_shows_help(self, capsys):
        with patch("sys.argv", ["cli"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0

    def test_trade_command(self, capsys):
        with patch("sys.argv", ["cli", "trade", "000001",
                                 "--buy", "2025-01-02", "--sell", "2025-01-08", "--qty", "1000"]):
            main()
        out = capsys.readouterr().out
        assert "000001" in out

    def test_info_command(self, capsys):
        with patch("sys.argv", ["cli", "info", "000001"]):
            main()
        out = capsys.readouterr().out
        assert "平安银行" in out

    def test_portfolio_command(self, capsys, tmp_path):
        trades = [
            {"code": "000001", "buy_date": "2025-01-02", "sell_date": "2025-01-08", "quantity": 1000},
        ]
        f = tmp_path / "trades.json"
        f.write_text(json.dumps(trades), encoding="utf-8")

        with patch("sys.argv", ["cli", "portfolio", str(f)]):
            main()
        out = capsys.readouterr().out
        assert "汇总统计" in out

    def test_interactive_command(self, capsys):
        with patch("sys.argv", ["cli", "interactive"]):
            with patch("builtins.input", side_effect=["q"]):
                main()
