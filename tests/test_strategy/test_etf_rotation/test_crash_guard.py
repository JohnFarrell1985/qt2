"""测试崩盘保护机制"""
import numpy as np
import pandas as pd

from src.strategy.etf_rotation.crash_guard import (
    AbsoluteMomentumGuard,
    BreadthMomentumGuard,
    CrashGuard,
    VolatilityGuard,
)


def _make_prices(n: int = 260, codes: list[str] | None = None, trend: float = 0.001) -> pd.DataFrame:
    codes = codes or ["C1", "C2"]
    dates = pd.bdate_range("2024-01-01", periods=n)
    rng = np.random.RandomState(42)
    data = {}
    for code in codes:
        daily = 1 + trend + rng.normal(0, 0.005, n)
        data[code] = 100.0 * np.cumprod(daily)
    return pd.DataFrame(data, index=dates)


class TestBreadthMomentumGuard:
    def test_all_positive(self):
        prices = _make_prices(260, trend=0.003)
        guard = BreadthMomentumGuard()
        frac = guard.evaluate(prices)
        assert frac == 0.0, "全部动量为正 → 0% 现金"

    def test_all_negative(self):
        prices = _make_prices(260, trend=-0.003)
        guard = BreadthMomentumGuard()
        frac = guard.evaluate(prices)
        assert frac == 1.0, "全部动量为负 → 100% 现金"

    def test_partial_negative(self):
        dates = pd.bdate_range("2024-01-01", periods=260)
        rng = np.random.RandomState(42)
        data = {
            "UP": 100.0 * np.cumprod(1 + 0.003 + rng.normal(0, 0.005, 260)),
            "DOWN": 100.0 * np.cumprod(1 - 0.003 + rng.normal(0, 0.005, 260)),
        }
        prices = pd.DataFrame(data, index=dates)
        guard = BreadthMomentumGuard()
        frac = guard.evaluate(prices)
        assert 0 < frac < 1, "部分为负 → 部分现金"

    def test_empty(self):
        guard = BreadthMomentumGuard()
        assert guard.evaluate(pd.DataFrame()) == 1.0


class TestAbsoluteMomentumGuard:
    def test_all_negative_triggers(self):
        prices = _make_prices(260, trend=-0.003)
        guard = AbsoluteMomentumGuard()
        assert guard.evaluate(prices) == 1.0

    def test_mixed_no_trigger(self):
        dates = pd.bdate_range("2024-01-01", periods=260)
        rng = np.random.RandomState(42)
        data = {
            "UP": 100.0 * np.cumprod(1 + 0.003 + rng.normal(0, 0.005, 260)),
            "DOWN": 100.0 * np.cumprod(1 - 0.003 + rng.normal(0, 0.005, 260)),
        }
        prices = pd.DataFrame(data, index=dates)
        guard = AbsoluteMomentumGuard()
        assert guard.evaluate(prices) == 0.0

    def test_empty(self):
        guard = AbsoluteMomentumGuard()
        assert guard.evaluate(pd.DataFrame()) == 1.0


class TestVolatilityGuard:
    def test_low_volatility(self):
        prices = _make_prices(260, trend=0.001)
        guard = VolatilityGuard()
        frac = guard.evaluate(prices, window=252)
        assert 0 <= frac <= 1

    def test_high_volatility(self):
        dates = pd.bdate_range("2024-01-01", periods=260)
        rng = np.random.RandomState(42)
        calm = 1 + 0.001 + rng.normal(0, 0.005, 230)
        volatile = 1 + 0.001 + rng.normal(0, 0.05, 30)
        daily = np.concatenate([calm, volatile])
        prices = pd.DataFrame(
            {"ETF": 100.0 * np.cumprod(daily)},
            index=dates,
        )
        guard = VolatilityGuard()
        frac = guard.evaluate(prices, window=252)
        assert frac > 0, "高波动期应触发一定现金比例"

    def test_empty(self):
        guard = VolatilityGuard()
        assert guard.evaluate(pd.DataFrame()) == 0.0

    def test_short_data(self):
        prices = _make_prices(10)
        guard = VolatilityGuard()
        assert guard.evaluate(prices) == 0.0


class TestCrashGuardComposite:
    def test_all_clear(self):
        prices = _make_prices(260, codes=["A", "B", "C"], trend=0.003)
        guard = CrashGuard(enable_breadth=True, enable_absolute=True, enable_volatility=True)
        frac = guard.evaluate(
            canary_prices=prices[["A"]],
            risk_prices=prices[["B", "C"]],
            all_prices=prices,
        )
        assert frac >= 0

    def test_all_disabled(self):
        guard = CrashGuard(enable_breadth=False, enable_absolute=False, enable_volatility=False)
        frac = guard.evaluate(pd.DataFrame(), pd.DataFrame(), pd.DataFrame())
        assert frac == 0.0

    def test_max_of_guards(self):
        down_prices = _make_prices(260, codes=["X", "Y"], trend=-0.003)
        guard = CrashGuard(enable_breadth=True, enable_absolute=True, enable_volatility=False)
        frac = guard.evaluate(
            canary_prices=down_prices,
            risk_prices=down_prices,
            all_prices=down_prices,
        )
        assert frac == 1.0, "金丝雀和绝对动量均为负 → 100% 现金"
