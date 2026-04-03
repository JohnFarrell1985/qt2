"""测试 BaseStrategy / Signal / StrategyRegistry"""
import pytest
from datetime import date

from src.strategy.base import BaseStrategy, Signal
from src.strategy.registry import StrategyRegistry, register_strategy


class DummyStrategy(BaseStrategy):
    tier = "rule"
    name = "test_dummy"
    description = "测试用策略"

    def generate_signals(self, trade_date, universe):
        return [
            Signal(
                trade_date=trade_date,
                code=code,
                direction="buy",
                score=1.0,
                strategy_name=self.name,
                strategy_tier=self.tier,
            )
            for code in universe[:2]
        ]


class TestSignal:
    def test_signal_defaults(self):
        s = Signal(trade_date=date(2025, 1, 1), code="000001.SZ", direction="buy")
        assert s.score == 0.0
        assert s.quantity == 0
        assert s.strategy_name == ""

    def test_signal_full(self):
        s = Signal(
            trade_date=date(2025, 1, 1),
            code="000001.SZ",
            direction="sell",
            score=3.5,
            quantity=100,
            strategy_name="test",
            strategy_tier="rule",
            reason="测试原因",
        )
        assert s.direction == "sell"
        assert s.reason == "测试原因"


class TestBaseStrategy:
    def test_abstract(self):
        with pytest.raises(TypeError):
            BaseStrategy()

    def test_concrete(self):
        strat = DummyStrategy(config={"top_n": 5})
        assert strat.tier == "rule"
        assert strat.config["top_n"] == 5
        info = strat.get_info()
        assert info["name"] == "test_dummy"

    def test_generate_signals(self):
        strat = DummyStrategy()
        signals = strat.generate_signals(date(2025, 6, 1), ["000001.SZ", "000002.SZ", "000003.SZ"])
        assert len(signals) == 2
        assert signals[0].direction == "buy"
        assert signals[0].code == "000001.SZ"


class TestRegistry:
    def setup_method(self):
        self.reg = StrategyRegistry()
        self.reg._classes.pop("test_dummy", None)

    def test_register_and_get(self):
        self.reg.register(DummyStrategy)
        assert self.reg.get("test_dummy") is DummyStrategy

    def test_create(self):
        self.reg.register(DummyStrategy)
        inst = self.reg.create("test_dummy", config={"x": 1})
        assert isinstance(inst, DummyStrategy)
        assert inst.config["x"] == 1

    def test_create_missing(self):
        with pytest.raises(KeyError):
            self.reg.create("nonexistent_strategy")

    def test_list_all(self):
        self.reg.register(DummyStrategy)
        items = self.reg.list_all()
        names = [i["name"] for i in items]
        assert "test_dummy" in names

    def test_list_by_tier(self):
        self.reg.register(DummyStrategy)
        rules = self.reg.list_by_tier("rule")
        assert any(i["name"] == "test_dummy" for i in rules)
        ml = self.reg.list_by_tier("ml")
        assert not any(i["name"] == "test_dummy" for i in ml)

    def test_decorator(self):
        @register_strategy
        class DecoratedStrategy(BaseStrategy):
            tier = "scoring"
            name = "test_decorated"
            description = "装饰器测试"
            def generate_signals(self, trade_date, universe):
                return []

        assert self.reg.get("test_decorated") is DecoratedStrategy
        # cleanup
        self.reg._classes.pop("test_decorated", None)
