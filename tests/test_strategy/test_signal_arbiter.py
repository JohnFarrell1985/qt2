"""测试 SignalArbiter"""
import pytest
from datetime import date

from src.strategy.base import Signal, HoldingPosition
from src.strategy.signal_arbiter import SignalArbiter


def _sig(code, direction="buy", score=1.0, strategy="test", **kw):
    return Signal(
        trade_date=date(2025, 6, 1),
        code=code, direction=direction, score=score,
        strategy_name=strategy, strategy_tier="rule",
        **kw,
    )


def _pos(code, **kw):
    defaults = {
        "buy_date": date(2025, 5, 28),
        "buy_price": 10.0, "quantity": 1000,
        "current_price": 10.0, "hold_days": 3,
    }
    defaults.update(kw)
    return HoldingPosition(code=code, **defaults)


class TestDedup:
    def test_same_stock_multi_strategy_buy(self):
        arbiter = SignalArbiter({"max_holdings": 5, "max_buy_per_day": 5})
        signals = [
            _sig("000001.SZ", score=3.0, strategy="momentum"),
            _sig("000001.SZ", score=2.0, strategy="reversal"),
        ]
        actions = arbiter.arbitrate(date(2025, 6, 1), signals)
        buy_actions = [a for a in actions if a.direction == "buy"]
        assert len(buy_actions) == 1
        assert len(buy_actions[0].signals) == 2

    def test_same_stock_multi_strategy_sell(self):
        arbiter = SignalArbiter()
        holdings = [_pos("000001.SZ")]
        signals = [
            _sig("000001.SZ", "sell", 90, "monitor"),
            _sig("000001.SZ", "sell", 80, "momentum"),
        ]
        actions = arbiter.arbitrate(date(2025, 6, 1), signals, holdings)
        sell_actions = [a for a in actions if a.direction == "sell"]
        assert len(sell_actions) == 1


class TestT1Filter:
    def test_cannot_sell_today_bought(self):
        arbiter = SignalArbiter()
        holdings = [_pos("000001.SZ", buy_date=date(2025, 6, 1))]
        signals = [
            _sig("000001.SZ", "sell", 100, "monitor"),
        ]
        actions = arbiter.arbitrate(date(2025, 6, 1), signals, holdings)
        sell_actions = [a for a in actions if a.direction == "sell"]
        assert len(sell_actions) == 0


class TestHoldingAware:
    def test_no_repeat_buy(self):
        arbiter = SignalArbiter({"max_holdings": 5, "max_buy_per_day": 5})
        holdings = [_pos("000001.SZ")]
        signals = [_sig("000001.SZ", score=5.0)]
        actions = arbiter.arbitrate(date(2025, 6, 1), signals, holdings)
        buy_actions = [a for a in actions if a.direction == "buy"]
        assert len(buy_actions) == 0

    def test_cannot_sell_unowned(self):
        arbiter = SignalArbiter()
        signals = [_sig("000002.SZ", "sell", 50)]
        actions = arbiter.arbitrate(date(2025, 6, 1), signals, [])
        sell_actions = [a for a in actions if a.direction == "sell"]
        assert len(sell_actions) == 0


class TestMaxHoldings:
    def test_respects_limit(self):
        arbiter = SignalArbiter({"max_holdings": 3, "max_buy_per_day": 5})
        holdings = [_pos("000001.SZ"), _pos("000002.SZ"), _pos("000003.SZ")]
        signals = [_sig("000004.SZ", score=10.0)]
        actions = arbiter.arbitrate(date(2025, 6, 1), signals, holdings)
        buy_actions = [a for a in actions if a.direction == "buy"]
        assert len(buy_actions) == 0

    def test_freed_slot_allows_buy(self):
        arbiter = SignalArbiter({"max_holdings": 3, "max_buy_per_day": 5})
        holdings = [_pos("000001.SZ"), _pos("000002.SZ"), _pos("000003.SZ")]
        signals = [
            _sig("000001.SZ", "sell", 90, "monitor"),
            _sig("000004.SZ", "buy", 5.0, "momentum"),
        ]
        actions = arbiter.arbitrate(date(2025, 6, 1), signals, holdings)
        sell_actions = [a for a in actions if a.direction == "sell"]
        buy_actions = [a for a in actions if a.direction == "buy"]
        assert len(sell_actions) == 1
        assert len(buy_actions) == 1


class TestSellPriority:
    def test_sell_before_buy(self):
        arbiter = SignalArbiter({"max_holdings": 5, "max_buy_per_day": 5})
        holdings = [_pos("000001.SZ")]
        signals = [
            _sig("000001.SZ", "sell", 90, "monitor"),
            _sig("000002.SZ", "buy", 5.0, "momentum"),
        ]
        actions = arbiter.arbitrate(date(2025, 6, 1), signals, holdings)
        assert actions[0].direction == "sell"
        assert actions[0].priority < actions[-1].priority
