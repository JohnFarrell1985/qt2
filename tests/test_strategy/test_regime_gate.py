"""测试 RegimeGate"""
import numpy as np
import pandas as pd
from datetime import date

from src.strategy.base import Signal
from src.strategy.regime_gate import RegimeGate


def _make_prices(trend: str, n: int = 300) -> pd.Series:
    """生成不同趋势的合成价格序列"""
    rng = np.random.default_rng(42)
    if trend == "up":
        daily_returns = rng.normal(0.003, 0.01, n)
    elif trend == "down":
        daily_returns = rng.normal(-0.003, 0.01, n)
    elif trend == "high_vol":
        daily_returns = rng.normal(0.0, 0.04, n)
    else:
        daily_returns = rng.normal(0.0, 0.008, n)
    prices = 100 * np.cumprod(1 + daily_returns)
    return pd.Series(prices)


def _sig(code: str, strategy: str, direction: str = "buy") -> Signal:
    return Signal(
        trade_date=date(2025, 6, 1),
        code=code, direction=direction,
        score=5.0, strategy_name=strategy,
        strategy_tier="rule",
    )


class TestDetectRegime:
    def test_uptrend(self):
        gate = RegimeGate(drift_window=63, drift_threshold=0.60)
        prices = _make_prices("up")
        regime = gate.detect_regime(prices)
        assert regime == "drift_up"

    def test_downtrend(self):
        gate = RegimeGate(drift_window=63, drift_threshold=0.60)
        prices = _make_prices("down")
        regime = gate.detect_regime(prices)
        assert regime == "drift_down"

    def test_normal(self):
        gate = RegimeGate(drift_window=63, drift_threshold=0.60)
        prices = _make_prices("normal")
        regime = gate.detect_regime(prices)
        assert regime in ("normal", "high_vol")

    def test_short_series_returns_normal(self):
        gate = RegimeGate(drift_window=63)
        prices = pd.Series([100.0, 101.0, 99.0])
        regime = gate.detect_regime(prices)
        assert regime == "normal"


class TestShouldPass:
    def test_momentum_drift_up_passes(self):
        gate = RegimeGate()
        sig = _sig("000001.SZ", "momentum")
        assert gate.should_pass(sig, "drift_up") is True

    def test_momentum_drift_down_blocked(self):
        gate = RegimeGate()
        sig = _sig("000001.SZ", "momentum")
        assert gate.should_pass(sig, "drift_down") is False

    def test_reversal_high_vol_passes(self):
        gate = RegimeGate()
        sig = _sig("000001.SZ", "reversal")
        assert gate.should_pass(sig, "high_vol") is True

    def test_reversal_drift_up_blocked(self):
        gate = RegimeGate()
        sig = _sig("000001.SZ", "reversal")
        assert gate.should_pass(sig, "drift_up") is False

    def test_unknown_strategy_passes(self):
        gate = RegimeGate()
        sig = _sig("000001.SZ", "custom_unknown")
        assert gate.should_pass(sig, "drift_down") is True

    def test_custom_map(self):
        custom = {"my_strat": ["high_vol"]}
        gate = RegimeGate(custom_map=custom)
        sig = _sig("000001.SZ", "my_strat")
        assert gate.should_pass(sig, "high_vol") is True
        assert gate.should_pass(sig, "normal") is False


class TestFilterSignals:
    def test_filters_in_drift_down(self):
        gate = RegimeGate()
        signals = [
            _sig("000001.SZ", "momentum"),
            _sig("000002.SZ", "reversal"),
            _sig("000003.SZ", "low_vol_dividend"),
        ]
        passed = gate.filter_signals(signals, "drift_down")
        names = [s.strategy_name for s in passed]
        assert "momentum" not in names
        assert "reversal" in names
        assert "low_vol_dividend" in names

    def test_all_pass_in_normal(self):
        gate = RegimeGate()
        signals = [
            _sig("000001.SZ", "momentum"),
            _sig("000002.SZ", "grid_trading"),
            _sig("000003.SZ", "cb_dual_low"),
        ]
        passed = gate.filter_signals(signals, "normal")
        assert len(passed) == 3

    def test_empty_signals(self):
        gate = RegimeGate()
        passed = gate.filter_signals([], "drift_up")
        assert passed == []

    def test_grid_trading_only_normal(self):
        gate = RegimeGate()
        sig = _sig("000001.SZ", "grid_trading")
        assert gate.filter_signals([sig], "normal") == [sig]
        assert gate.filter_signals([sig], "drift_up") == []
        assert gate.filter_signals([sig], "drift_down") == []
        assert gate.filter_signals([sig], "high_vol") == []
