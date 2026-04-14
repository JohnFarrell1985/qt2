"""E2E: RegimeGate — 用真实沪深300指数价格做 regime 检测与信号过滤"""
from datetime import date

from src.strategy.regime_gate import RegimeGate
from src.strategy.base import Signal


class TestRegimeDetectionWithRealIndex:
    """用真实指数价格验证 regime 检测"""

    def test_detect_regime_returns_valid_state(self, real_index_prices):
        gate = RegimeGate()
        regime = gate.detect_regime(real_index_prices)
        assert regime in ("drift_up", "drift_down", "high_vol", "normal"), (
            f"Unexpected regime: {regime}"
        )

    def test_regime_stable_for_consecutive_windows(self, real_index_prices):
        """滑动窗口检测, 相邻时间点的 regime 不应剧烈跳跃"""
        gate = RegimeGate(drift_window=63)
        prices = real_index_prices
        n = len(prices)
        regimes = []
        start = gate.drift_window + 2
        for end in range(start, n, 20):
            window = prices.iloc[:end]
            r = gate.detect_regime(window)
            regimes.append(r)

        assert len(regimes) > 3, (
            f"Should have enough windows: n={n}, start={start}, got {len(regimes)}"
        )

        transitions = sum(1 for i in range(1, len(regimes)) if regimes[i] != regimes[i - 1])
        transition_rate = transitions / (len(regimes) - 1) if len(regimes) > 1 else 0
        assert transition_rate < 0.8, (
            f"Regime transitions too frequent ({transition_rate:.2%}), "
            f"regimes: {regimes}"
        )

    def test_short_series_returns_normal(self):
        """不足 drift_window 的短序列应返回 normal"""
        import pandas as pd
        short = pd.Series([100.0] * 10)
        gate = RegimeGate(drift_window=63)
        assert gate.detect_regime(short) == "normal"

    def test_regime_with_different_thresholds(self, real_index_prices):
        """不同阈值应产生不同灵敏度"""
        gate_strict = RegimeGate(drift_threshold=0.70)
        gate_loose = RegimeGate(drift_threshold=0.55)

        r_strict = gate_strict.detect_regime(real_index_prices)
        r_loose = gate_loose.detect_regime(real_index_prices)

        assert r_strict in ("drift_up", "drift_down", "high_vol", "normal")
        assert r_loose in ("drift_up", "drift_down", "high_vol", "normal")


class TestSignalFilteringWithRealRegime:
    """用真实 regime 做信号过滤"""

    def test_momentum_blocked_in_drift_down(self, real_index_prices):
        gate = RegimeGate()
        sig = Signal(
            trade_date=date(2025, 6, 1),
            code="000001",
            direction="buy",
            score=0.8,
            strategy_name="momentum",
        )
        assert not gate.should_pass(sig, "drift_down"), (
            "momentum should be blocked in drift_down"
        )

    def test_reversal_passes_in_drift_down(self):
        gate = RegimeGate()
        sig = Signal(
            trade_date=date(2025, 6, 1),
            code="000001",
            direction="buy",
            score=0.7,
            strategy_name="reversal",
        )
        assert gate.should_pass(sig, "drift_down")

    def test_unknown_strategy_always_passes(self):
        gate = RegimeGate()
        sig = Signal(
            trade_date=date(2025, 6, 1),
            code="600519",
            direction="buy",
            score=0.5,
            strategy_name="unknown_strategy_xyz",
        )
        for regime in ("drift_up", "drift_down", "high_vol", "normal"):
            assert gate.should_pass(sig, regime)

    def test_filter_signals_with_real_regime(self, real_index_prices):
        gate = RegimeGate()
        regime = gate.detect_regime(real_index_prices)

        signals = [
            Signal(trade_date=date(2025, 6, 1), code="000001", direction="buy",
                   score=0.8, strategy_name="momentum"),
            Signal(trade_date=date(2025, 6, 1), code="600519", direction="buy",
                   score=0.7, strategy_name="reversal"),
            Signal(trade_date=date(2025, 6, 1), code="300750", direction="buy",
                   score=0.6, strategy_name="low_vol_dividend"),
            Signal(trade_date=date(2025, 6, 1), code="000858", direction="buy",
                   score=0.5, strategy_name="grid_trading"),
        ]

        filtered = gate.filter_signals(signals, regime)
        assert len(filtered) <= len(signals)
        assert all(gate.should_pass(s, regime) for s in filtered)

        if regime == "normal":
            assert len(filtered) == len(signals), (
                "All strategies should pass in normal regime"
            )
