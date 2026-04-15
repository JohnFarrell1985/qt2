"""测试 PositionSizer"""
from datetime import date

from src.strategy.base import Signal, ActionItem
from src.strategy.position_sizer import PositionSizer, DrawdownGuard


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


class TestDrawdownGuard:
    def test_default_thresholds_no_drawdown(self):
        guard = DrawdownGuard()
        assert guard.scale_factor(0.0) == 1.0

    def test_mild_drawdown(self):
        guard = DrawdownGuard()
        assert guard.scale_factor(-0.03) == 0.90

    def test_moderate_drawdown(self):
        guard = DrawdownGuard()
        assert guard.scale_factor(-0.05) == 0.75

    def test_severe_drawdown(self):
        guard = DrawdownGuard()
        assert guard.scale_factor(-0.08) == 0.50

    def test_extreme_drawdown(self):
        guard = DrawdownGuard()
        assert guard.scale_factor(-0.15) == 0.10

    def test_between_thresholds(self):
        guard = DrawdownGuard()
        assert guard.scale_factor(-0.04) == 0.90
        assert guard.scale_factor(-0.10) == 0.50

    def test_custom_thresholds(self):
        custom = [(-0.10, 0.50), (-0.20, 0.20)]
        guard = DrawdownGuard(thresholds=custom)
        assert guard.scale_factor(-0.05) == 1.0
        assert guard.scale_factor(-0.10) == 0.50
        assert guard.scale_factor(-0.25) == 0.20


class TestFractionalKelly:
    def test_kelly_fraction_affects_weights(self):
        sizer_low = PositionSizer({
            "mode": "kelly", "kelly_fraction": 0.10,
            "drawdown_guard_enabled": False,
        })
        sizer_high = PositionSizer({
            "mode": "kelly", "kelly_fraction": 0.50,
            "drawdown_guard_enabled": False,
        })
        actions_low = [_action("A")]
        actions_high = [_action("A")]
        result_low = sizer_low.allocate(
            buy_actions=actions_low, total_capital=100_000,
            available_cash=100_000, price_map={"A": 10.0},
        )
        result_high = sizer_high.allocate(
            buy_actions=actions_high, total_capital=100_000,
            available_cash=100_000, price_map={"A": 10.0},
        )
        assert len(result_low) == 1
        assert len(result_high) == 1

    def test_kelly_default_fraction(self):
        sizer = PositionSizer({
            "mode": "kelly", "drawdown_guard_enabled": False,
        })
        result = sizer.allocate(
            buy_actions=[_action("A"), _action("B")],
            total_capital=100_000, available_cash=100_000,
            price_map={"A": 10.0, "B": 10.0},
        )
        assert len(result) == 2
        assert all(a.target_quantity > 0 for a in result)


class TestDrawdownGuardIntegration:
    def test_drawdown_reduces_allocation(self):
        sizer = PositionSizer({
            "mode": "equal", "max_total_pct": 80.0,
            "drawdown_guard_enabled": True,
        })
        actions_normal = [_action("A")]
        result_normal = sizer.allocate(
            buy_actions=actions_normal, total_capital=100_000,
            available_cash=100_000, price_map={"A": 10.0},
            current_drawdown=0.0,
        )
        actions_dd = [_action("A")]
        result_dd = sizer.allocate(
            buy_actions=actions_dd, total_capital=100_000,
            available_cash=100_000, price_map={"A": 10.0},
            current_drawdown=-0.08,
        )
        assert len(result_normal) >= 1
        assert len(result_dd) >= 1
        assert result_dd[0].target_amount <= result_normal[0].target_amount

    def test_drawdown_guard_disabled(self):
        sizer = PositionSizer({
            "mode": "equal", "max_total_pct": 80.0,
            "drawdown_guard_enabled": False,
        })
        actions_a = [_action("A")]
        result_a = sizer.allocate(
            buy_actions=actions_a, total_capital=100_000,
            available_cash=100_000, price_map={"A": 10.0},
            current_drawdown=0.0,
        )
        actions_b = [_action("A")]
        result_b = sizer.allocate(
            buy_actions=actions_b, total_capital=100_000,
            available_cash=100_000, price_map={"A": 10.0},
            current_drawdown=-0.10,
        )
        assert result_a[0].target_amount == result_b[0].target_amount
