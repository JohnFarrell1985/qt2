"""strategy_runner 单元测试"""
from datetime import date
from unittest.mock import patch, MagicMock

import pytest

from backtest.strategy_runner import (
    run_strategy, run_continuous, StrategyConfig, StrategyResult, DayTrade, _is_limit_up,
)
from backtest.stock_picker import MockPicker, RandomPicker
from backtest.fees import FeeConfig


# ======== _is_limit_up ========

class TestIsLimitUp:
    def test_limit_up_exact(self):
        assert _is_limit_up(10.98, 10.0, 9.8) is True

    def test_limit_up_above(self):
        assert _is_limit_up(11.0, 10.0, 9.8) is True

    def test_not_limit_up(self):
        assert _is_limit_up(10.5, 10.0, 9.8) is False

    def test_zero_pre_close(self):
        assert _is_limit_up(10.0, 0, 9.8) is False

    def test_none_pre_close(self):
        assert _is_limit_up(10.0, None, 9.8) is False

    def test_negative_pre_close(self):
        assert _is_limit_up(10.0, -1.0, 9.8) is False

    def test_custom_threshold_5pct(self):
        # ST股 5%涨停
        assert _is_limit_up(10.5, 10.0, 5.0) is True
        assert _is_limit_up(10.4, 10.0, 5.0) is False


# ======== StrategyConfig ========

class TestStrategyConfig:
    def test_defaults(self):
        c = StrategyConfig()
        assert c.initial_capital == 1_000_000.0
        assert c.max_position_pct == 0.30
        assert c.max_total_position_pct == 0.80
        assert c.max_holdings == 3
        assert c.limit_up_threshold == 9.8

    def test_custom(self):
        c = StrategyConfig(initial_capital=500_000, max_holdings=1)
        assert c.initial_capital == 500_000
        assert c.max_holdings == 1


# ======== DayTrade ========

class TestDayTrade:
    def test_basic(self):
        t = DayTrade(
            code="000001", pick_date=date(2025, 1, 2), buy_date=date(2025, 1, 3),
            sell_date=date(2025, 1, 6), buy_price=10.2, sell_price=10.5,
            quantity=1000, buy_amount=10205.0, sell_amount=10490.0,
            fees=15.0, profit=285.0, profit_pct=2.79,
        )
        assert t.code == "000001"
        assert t.skipped is False

    def test_skipped(self):
        t = DayTrade(
            code="000099", pick_date=date(2025, 1, 2), buy_date=date(2025, 1, 3),
            sell_date=date(2025, 1, 6), buy_price=22.0, sell_price=0,
            quantity=0, buy_amount=0, sell_amount=0, fees=0,
            profit=0, profit_pct=0, skipped=True, skip_reason="涨停开盘",
        )
        assert t.skipped is True
        assert "涨停" in t.skip_reason


# ======== StrategyResult ========

class TestStrategyResult:
    def test_to_dict(self):
        r = StrategyResult(
            config=StrategyConfig(),
            start_date=date(2025, 1, 1), end_date=date(2025, 12, 31),
            initial_capital=1_000_000, final_capital=1_050_000,
            total_return=50_000, total_return_pct=5.0, annualized_return_pct=5.0,
            total_trades=10, win_trades=6, lose_trades=4, skipped_trades=2,
            win_rate=60.0, total_fees=500.0,
            max_single_profit=10000, max_single_loss=-5000,
            avg_profit_per_trade=5000, avg_holding_days=1.0,
        )
        d = r.to_dict()
        assert d["total_trades"] == 10
        assert "5.00%" in d["total_return_pct"]


# ======== run_strategy ========

class TestRunStrategy:
    def test_basic_mock_run(self):
        """基本 mock 选股回测，使用已有的 conftest mock 数据"""
        schedule = {
            date(2025, 1, 2): ["000001"],
        }
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(initial_capital=100_000)

        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
            config=config,
        )

        assert isinstance(result, StrategyResult)
        assert result.initial_capital == 100_000
        assert result.start_date == date(2025, 1, 2)
        assert result.end_date == date(2025, 1, 8)

    def test_no_picks_no_trades(self):
        """选股器不推荐任何股票"""
        picker = MockPicker(schedule={})
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
        )
        assert result.total_trades == 0
        assert result.final_capital == result.initial_capital

    def test_limit_up_skip(self):
        """涨停开盘应被跳过"""
        # 000099 在 1/3 开盘价 22.0, 前收 20.0 → 涨幅 10% > 9.8%
        schedule = {
            date(2025, 1, 2): ["000099"],
        }
        picker = MockPicker(schedule=schedule)
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
        )
        assert result.total_trades == 0
        assert result.skipped_trades >= 1
        assert any("涨停" in s.skip_reason for s in result.skipped)

    def test_multiple_stocks_per_day(self):
        """一天选多只股票"""
        schedule = {
            date(2025, 1, 2): ["000001", "000002"],
        }
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(initial_capital=200_000)
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
            config=config,
        )
        # 两只都有数据，都应该被买入
        assert result.total_trades == 2

    def test_equity_curve_exists(self):
        """净值曲线应有数据"""
        schedule = {date(2025, 1, 2): ["000001"]}
        picker = MockPicker(schedule=schedule)
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
        )
        assert len(result.equity_curve) > 0
        for point in result.equity_curve:
            assert "date" in point
            assert "capital" in point

    def test_multiple_pick_dates(self):
        """多个交易日分别选股"""
        schedule = {
            date(2025, 1, 2): ["000001"],
            date(2025, 1, 6): ["000002"],
        }
        picker = MockPicker(schedule=schedule)
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
        )
        assert result.total_trades >= 1

    def test_insufficient_capital(self):
        """资金不足以买入时跳过"""
        schedule = {date(2025, 1, 2): ["600519"]}
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(initial_capital=1000)
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
            config=config,
        )
        assert result.total_trades == 0

    def test_no_trading_dates_raises(self):
        """日期范围内无交易日应报错"""
        picker = MockPicker(schedule={})
        with pytest.raises(ValueError, match="没有交易日"):
            run_strategy(
                picker=picker,
                start_date=date(2020, 1, 1),
                end_date=date(2020, 1, 5),
            )

    def test_win_lose_counts(self):
        """检查盈亏笔数统计"""
        schedule = {
            date(2025, 1, 2): ["000001"],  # 买@10.2(1/3开盘) 卖@10.5(1/6开盘) → 盈利
        }
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(initial_capital=100_000)
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
            config=config,
        )
        if result.total_trades > 0:
            assert result.win_trades + result.lose_trades == result.total_trades

    def test_max_holdings_respected(self):
        """不超过最大持仓数"""
        schedule = {
            date(2025, 1, 2): ["000001", "000002", "600519", "000099"],
        }
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(initial_capital=5_000_000, max_holdings=2)
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
            config=config,
        )
        # 000099 涨停跳过, 其余3只取前2只
        assert result.total_trades <= 2

    def test_fees_accumulated(self):
        """手续费应被累计"""
        schedule = {date(2025, 1, 2): ["000001"]}
        picker = MockPicker(schedule=schedule)
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
        )
        if result.total_trades > 0:
            assert result.total_fees > 0

    def test_trade_detail_fields(self):
        """检查交易明细字段完整性"""
        schedule = {date(2025, 1, 2): ["000001"]}
        picker = MockPicker(schedule=schedule)
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
        )
        if result.trades:
            t = result.trades[0]
            assert t.code == "000001"
            assert t.pick_date == date(2025, 1, 2)
            assert t.buy_price > 0
            assert t.sell_price > 0
            assert t.quantity > 0
            assert t.buy_amount > 0
            assert t.sell_amount > 0

    def test_prompt_passed_to_picker(self):
        """提示词应传递给选股器"""
        called_prompts = []

        class TrackedPicker(MockPicker):
            def pick(self, trade_date, prompt=""):
                called_prompts.append(prompt)
                return super().pick(trade_date, prompt)

        schedule = {date(2025, 1, 2): ["000001"]}
        picker = TrackedPicker(schedule=schedule)
        run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
            prompt="test prompt",
        )
        assert any("test prompt" in p for p in called_prompts)

    def test_random_picker_integration(self):
        """RandomPicker 集成测试"""
        pool = ["000001", "000002"]
        picker = RandomPicker(pool, pick_count=1, seed=42)
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
        )
        assert isinstance(result, StrategyResult)

    def test_annualized_return_calculated(self):
        """年化收益率应被计算"""
        schedule = {date(2025, 1, 2): ["000001"]}
        picker = MockPicker(schedule=schedule)
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
        )
        # 年化收益率应是一个数字 (即使区间很短)
        assert isinstance(result.annualized_return_pct, float)

    def test_sell_date_beyond_end_date(self):
        """卖出日超出回测范围时跳过"""
        # 只有 1/8 作为最后一天，1/2选股 → 1/3买 → 1/6卖 OK
        # 但 1/7选股 → 1/8买 → 无下一个交易日 → 跳过
        schedule = {
            date(2025, 1, 2): ["000001"],
            date(2025, 1, 7): ["000001"],  # 卖出日超出范围
        }
        picker = MockPicker(schedule=schedule)
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
        )
        # 至少第一笔能完成
        assert result.total_trades >= 1

    def test_stock_no_data_skipped(self):
        """股票无数据时跳过"""
        schedule = {date(2025, 1, 2): ["999999"]}
        picker = MockPicker(schedule=schedule)
        result = run_strategy(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
        )
        assert result.total_trades == 0
        assert result.skipped_trades >= 1


# ================================================================
#  run_continuous 连续持仓策略
# ================================================================

class TestRunContinuous:
    def test_basic_continuous(self):
        """基本连续持仓: 选一只股持有到不再选中"""
        schedule = {
            date(2025, 1, 2): ["000001"],
            date(2025, 1, 3): ["000001"],   # 续持
            date(2025, 1, 6): ["000002"],   # 换股: 卖000001, 买000002
        }
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(initial_capital=100_000, max_holdings=2)
        result = run_continuous(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
            config=config,
        )
        assert isinstance(result, StrategyResult)
        # 000001 应该被买入一次卖出一次, 000002 被买入后在结束时清仓
        assert result.total_trades >= 1

    def test_hold_same_stock(self):
        """连续选中同一只股票 → 只买一次, 不反复交易"""
        schedule = {
            date(2025, 1, 2): ["000001"],
            date(2025, 1, 3): ["000001"],
            date(2025, 1, 6): ["000001"],
            date(2025, 1, 7): ["000001"],
        }
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(initial_capital=100_000)
        result = run_continuous(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
            config=config,
        )
        # 始终持有000001, 最终清仓算1笔交易
        assert result.total_trades == 1
        t = result.trades[0]
        assert t.code == "000001"
        assert t.holding_days > 1

    def test_switch_stock(self):
        """换股: 前一天选A, 今天选B → 卖A买B"""
        schedule = {
            date(2025, 1, 2): ["000001"],
            date(2025, 1, 3): ["000002"],
        }
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(initial_capital=100_000)
        result = run_continuous(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
            config=config,
        )
        codes = [t.code for t in result.trades]
        assert "000001" in codes
        assert "000002" in codes

    def test_no_picks_sells_all(self):
        """某天无选股 → 卖出全部持仓"""
        schedule = {
            date(2025, 1, 2): ["000001"],
            date(2025, 1, 3): [],     # 不选股 → 卖掉000001
        }
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(initial_capital=100_000)
        result = run_continuous(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
            config=config,
        )
        assert result.total_trades >= 1

    def test_limit_up_skip_in_continuous(self):
        """连续持仓中涨停开盘仍然跳过买入"""
        # 000099 在 1/3 涨停开盘 (open=22, pre_close=20, +10%)
        schedule = {
            date(2025, 1, 2): ["000099"],
        }
        picker = MockPicker(schedule=schedule)
        result = run_continuous(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
        )
        assert result.total_trades == 0
        assert result.skipped_trades >= 1

    def test_multiple_holdings(self):
        """同时持有多只股票"""
        schedule = {
            date(2025, 1, 2): ["000001", "000002"],
            date(2025, 1, 3): ["000001", "000002"],   # 续持两只
            date(2025, 1, 6): ["000001"],              # 卖000002, 留000001
        }
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(initial_capital=200_000, max_holdings=3)
        result = run_continuous(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
            config=config,
        )
        assert result.total_trades >= 2

    def test_end_of_period_liquidation(self):
        """回测结束时清仓"""
        schedule = {
            date(2025, 1, 2): ["000001"],
            date(2025, 1, 3): ["000001"],
            date(2025, 1, 6): ["000001"],
            date(2025, 1, 7): ["000001"],
            date(2025, 1, 8): ["000001"],  # 持仓到最后
        }
        picker = MockPicker(schedule=schedule)
        result = run_continuous(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
        )
        # 最终会被清仓
        assert result.total_trades >= 1
        assert result.final_capital > 0

    def test_equity_curve_has_holdings(self):
        """净值曲线应包含持仓信息"""
        schedule = {date(2025, 1, 2): ["000001"]}
        picker = MockPicker(schedule=schedule)
        result = run_continuous(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
        )
        assert len(result.equity_curve) > 0
        for pt in result.equity_curve:
            assert "holdings" in pt

    def test_no_trading_dates_raises(self):
        """无交易日应报错"""
        picker = MockPicker(schedule={})
        with pytest.raises(ValueError, match="没有交易日"):
            run_continuous(
                picker=picker,
                start_date=date(2020, 1, 1),
                end_date=date(2020, 1, 5),
            )

    def test_prompt_template_mode(self):
        """使用 prompt_template 时每天替换日期"""
        schedule = {
            date(2025, 1, 2): ["000001"],
            date(2025, 1, 3): ["000001"],
        }
        picker = MockPicker(schedule=schedule)
        result = run_continuous(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
            prompt_template="prompt1.txt",
        )
        assert isinstance(result, StrategyResult)

    def test_avg_holding_days(self):
        """平均持仓天数应大于1（续持场景）"""
        schedule = {
            date(2025, 1, 2): ["000001"],
            date(2025, 1, 3): ["000001"],
            date(2025, 1, 6): ["000001"],
            date(2025, 1, 7): ["000002"],  # 换股
        }
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(initial_capital=100_000)
        result = run_continuous(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
            config=config,
        )
        # 000001 持仓多天, 000002 持仓1天+清仓
        assert result.avg_holding_days >= 1.0

    def test_insufficient_capital(self):
        """资金不足无法买入"""
        schedule = {date(2025, 1, 2): ["600519"]}  # 茅台 1500+/股
        picker = MockPicker(schedule=schedule)
        config = StrategyConfig(initial_capital=1000)
        result = run_continuous(
            picker=picker,
            start_date=date(2025, 1, 2),
            end_date=date(2025, 1, 8),
            config=config,
        )
        assert result.total_trades == 0
