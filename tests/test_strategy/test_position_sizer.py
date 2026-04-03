"""测试 PositionSizer"""
import pytest
from datetime import date

from src.strategy.base import Signal, ActionItem
from src.strategy.position_sizer import PositionSizer


def _action(code, direction="buy", score=5.0):
    sig = Signal(
        trade_date=date(2025, 6, 1),
        code=code, direction=direction, score=score,
        strategy_name="test", strategy_tier="rule",
    )
    return ActionItem(code=code, direction=direction, signals=[sig])


class TestEqualWeight:
    def test_allocates_evenly(self):
        sizer = PositionSizer({"mode": "equal", "max_total_pct": 80.0})
        actions = [_action("A"), _action("B")]
        result = sizer.allocate(
            buy_actions=actions,
            total_capital=100_000,
            available_cash=100_000,
            current_position_pct=0,
            price_map={"A": 10.0, "B": 20.0},
        )
        assert len(result) == 2
        assert result[0].target_quantity > 0
        assert result[1].target_quantity > 0
        total_pct = sum(a.target_weight_pct for a in result)
        assert total_pct <= 80.0 + 0.1

    def test_respects_max_single_pct(self):
        sizer = PositionSizer({"mode": "equal", "max_single_pct": 15.0})
        result = sizer.allocate(
            buy_actions=[_action("A")],
            total_capital=100_000,
            available_cash=100_000,
            current_position_pct=0,
            price_map={"A": 10.0},
        )
        assert len(result) == 1
        assert result[0].target_weight_pct <= 15.0 + 0.1


class TestATRWeight:
    def test_low_vol_gets_more(self):
        sizer = PositionSizer({"mode": "atr"})
        actions = [_action("A"), _action("B")]
        result = sizer.allocate(
            buy_actions=actions,
            total_capital=100_000,
            available_cash=100_000,
            current_position_pct=0,
            atr_map={"A": 0.5, "B": 2.0},
            price_map={"A": 10.0, "B": 10.0},
        )
        assert len(result) == 2
        assert result[0].target_weight_pct > result[1].target_weight_pct


class TestKelly:
    def test_allocates(self):
        sizer = PositionSizer({"mode": "kelly"})
        actions = [_action("A"), _action("B")]
        result = sizer.allocate(
            buy_actions=actions,
            total_capital=100_000,
            available_cash=100_000,
            current_position_pct=0,
            price_map={"A": 10.0, "B": 10.0},
        )
        assert len(result) == 2
        assert all(a.target_quantity > 0 for a in result)


class TestCashConstraint:
    def test_skips_when_no_cash(self):
        sizer = PositionSizer({"mode": "equal"})
        result = sizer.allocate(
            buy_actions=[_action("A"), _action("B")],
            total_capital=100_000,
            available_cash=0,
            current_position_pct=0,
            price_map={"A": 10.0, "B": 10.0},
        )
        assert len(result) == 0


class TestLotSize:
    def test_rounds_to_100(self):
        sizer = PositionSizer({
            "mode": "equal", "lot_size": 100,
            "max_single_pct": 50.0, "max_total_pct": 80.0,
        })
        result = sizer.allocate(
            buy_actions=[_action("A")],
            total_capital=100_000,
            available_cash=100_000,
            current_position_pct=0,
            price_map={"A": 15.37},
        )
        if result:
            assert result[0].target_quantity % 100 == 0
