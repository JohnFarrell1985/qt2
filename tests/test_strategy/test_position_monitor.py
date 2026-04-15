"""测试 PositionMonitor"""
from datetime import date

from src.strategy.base import HoldingPosition
from src.strategy.position_monitor import PositionMonitor


def _make_pos(**kwargs):
    defaults = {
        "code": "000001.SZ",
        "buy_date": date(2025, 5, 20),
        "buy_price": 10.0,
        "quantity": 1000,
        "current_price": 10.0,
        "highest_price": 10.0,
        "hold_days": 3,
        "strategy_name": "momentum",
        "profit_pct": 0.0,
        "can_sell": True,
    }
    defaults.update(kwargs)
    return HoldingPosition(**defaults)


class TestStopLoss:
    def test_triggers_on_loss(self):
        monitor = PositionMonitor({"default_stop_loss_pct": -8.0})
        pos = _make_pos(current_price=9.1, profit_pct=-9.0)
        signals = monitor.scan(date(2025, 6, 1), [pos])
        assert len(signals) == 1
        assert signals[0].direction == "sell"
        assert "止损" in signals[0].reason

    def test_no_trigger_on_small_loss(self):
        monitor = PositionMonitor({"default_stop_loss_pct": -8.0})
        pos = _make_pos(current_price=9.5, profit_pct=-5.0)
        signals = monitor.scan(date(2025, 6, 1), [pos])
        assert len(signals) == 0


class TestTakeProfit:
    def test_triggers_on_profit(self):
        monitor = PositionMonitor({"default_take_profit_pct": 15.0})
        pos = _make_pos(current_price=12.0, profit_pct=20.0)
        signals = monitor.scan(date(2025, 6, 1), [pos])
        assert len(signals) == 1
        assert "止盈" in signals[0].reason


class TestTrailingStop:
    def test_triggers_on_drawdown(self):
        monitor = PositionMonitor({
            "enable_trailing_stop": True,
            "default_trailing_stop_pct": 5.0,
            "default_stop_loss_pct": -20.0,
            "default_take_profit_pct": 50.0,
        })
        pos = _make_pos(
            current_price=11.3, highest_price=12.0,
            profit_pct=13.0,
        )
        signals = monitor.scan(date(2025, 6, 1), [pos])
        assert len(signals) == 1
        assert "移动止损" in signals[0].reason


class TestExpiryCleanup:
    def test_triggers_on_hold_too_long(self):
        monitor = PositionMonitor({
            "default_max_hold_days": 10,
            "default_stop_loss_pct": -20.0,
            "default_take_profit_pct": 50.0,
            "force_sell_on_expiry": True,
        })
        pos = _make_pos(hold_days=12, profit_pct=-2.0)
        signals = monitor.scan(date(2025, 6, 1), [pos])
        assert len(signals) == 1
        assert "超期" in signals[0].reason

    def test_no_trigger_if_profitable(self):
        monitor = PositionMonitor({
            "default_max_hold_days": 10,
            "default_stop_loss_pct": -20.0,
            "default_take_profit_pct": 50.0,
            "force_sell_on_expiry": True,
            "expiry_loss_threshold": 0.0,
        })
        pos = _make_pos(hold_days=12, current_price=11.0, profit_pct=10.0)
        signals = monitor.scan(date(2025, 6, 1), [pos])
        assert len(signals) == 0


class TestT1Constraint:
    def test_cannot_sell_today_bought(self):
        monitor = PositionMonitor()
        pos = _make_pos(buy_date=date(2025, 6, 1), profit_pct=-15.0, current_price=8.5)
        signals = monitor.scan(date(2025, 6, 1), [pos])
        assert len(signals) == 0

    def test_can_sell_if_not_today(self):
        monitor = PositionMonitor({"default_stop_loss_pct": -8.0})
        pos = _make_pos(
            buy_date=date(2025, 5, 30), profit_pct=-10.0,
            current_price=9.0,
        )
        signals = monitor.scan(date(2025, 6, 1), [pos])
        assert len(signals) == 1
