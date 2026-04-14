"""Tests for BaseFactor ABC and FactorRegistry (P1-30)"""
import pandas as pd
import pytest

from src.factor.base import BaseFactor, FactorRegistry, register_factor


class DummyFactor(BaseFactor):
    @property
    def name(self):
        return "dummy_mom_20"

    @property
    def category(self):
        return "momentum"

    @property
    def lookback_days(self):
        return 20

    def compute(self, df):
        return df["close"].pct_change(20)


class AnotherFactor(BaseFactor):
    @property
    def name(self):
        return "dummy_vol_20"

    @property
    def category(self):
        return "volatility"

    def compute(self, df):
        return df["close"].pct_change().rolling(20).std()


class TestBaseFactor:
    def test_abstract_methods(self):
        with pytest.raises(TypeError):
            BaseFactor()

    def test_concrete_factor(self):
        f = DummyFactor()
        assert f.name == "dummy_mom_20"
        assert f.category == "momentum"
        assert f.version == "1.0.0"
        assert f.data_source == "ohlcv"
        assert f.lookback_days == 20

    def test_compute(self):
        f = DummyFactor()
        df = pd.DataFrame({"close": list(range(100, 130))})
        result = f.compute(df)
        assert len(result) == 30
        assert pd.notna(result.iloc[-1])


class TestFactorRegistry:
    @pytest.fixture(autouse=True)
    def fresh_registry(self):
        registry = FactorRegistry()
        saved = dict(registry._factors)
        registry.clear()
        yield registry
        registry.clear()
        registry._factors.update(saved)

    def test_register_and_get(self, fresh_registry):
        f = DummyFactor()
        fresh_registry.register(f)
        assert fresh_registry.get("dummy_mom_20") is f

    def test_register_class(self, fresh_registry):
        fresh_registry.register_class(DummyFactor)
        assert fresh_registry.get("dummy_mom_20") is not None

    def test_list_all(self, fresh_registry):
        fresh_registry.register(DummyFactor())
        fresh_registry.register(AnotherFactor())
        items = fresh_registry.list_all()
        assert len(items) == 2
        names = {i["name"] for i in items}
        assert "dummy_mom_20" in names
        assert "dummy_vol_20" in names

    def test_list_by_category(self, fresh_registry):
        fresh_registry.register(DummyFactor())
        fresh_registry.register(AnotherFactor())
        mom_factors = fresh_registry.list_by_category("momentum")
        assert len(mom_factors) == 1
        assert mom_factors[0].name == "dummy_mom_20"

    def test_list_names(self, fresh_registry):
        fresh_registry.register(DummyFactor())
        fresh_registry.register(AnotherFactor())
        assert "dummy_mom_20" in fresh_registry.list_names()
        assert fresh_registry.list_names("volatility") == ["dummy_vol_20"]

    def test_compute_all(self, fresh_registry):
        fresh_registry.register(DummyFactor())
        fresh_registry.register(AnotherFactor())
        df = pd.DataFrame({"close": list(range(100, 160))})
        result = fresh_registry.compute_all(df)
        assert "dummy_mom_20" in result.columns
        assert "dummy_vol_20" in result.columns

    def test_register_factor_decorator(self, fresh_registry):
        @register_factor
        class DecoratedFactor(BaseFactor):
            @property
            def name(self):
                return "decorated_test"

            @property
            def category(self):
                return "test"

            def compute(self, df):
                return df["close"] * 0

        assert fresh_registry.get("decorated_test") is not None

    def test_register_no_name(self, fresh_registry):
        class BadFactor(BaseFactor):
            @property
            def name(self):
                return ""

            @property
            def category(self):
                return "test"

            def compute(self, df):
                return df["close"]

        with pytest.raises(ValueError):
            fresh_registry.register(BadFactor())
