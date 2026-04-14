"""Tests for src/factor/auto_screen.py"""

import numpy as np
import pandas as pd
import pytest

from src.factor.auto_screen import AutoFactorScreen


def _make_multi_index_data(n_dates: int = 60, n_stocks: int = 50, n_factors: int = 10, seed: int = 42):
    """生成合成的 MultiIndex(trade_date, stock_code) 因子矩阵 + 未来收益"""
    rng = np.random.RandomState(seed)

    dates = pd.date_range("2024-01-01", periods=n_dates, freq="B")
    codes = [f"00{i:04d}.SZ" for i in range(n_stocks)]

    idx = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "stock_code"])

    factors = {}
    for i in range(n_factors):
        factors[f"factor_{i}"] = rng.randn(len(idx))

    factor_matrix = pd.DataFrame(factors, index=idx)

    signal_factor = factor_matrix["factor_0"]
    noise = rng.randn(len(idx)) * 0.05
    forward_returns = pd.Series(signal_factor.values * 0.02 + noise, index=idx, name="forward_return")

    return factor_matrix, forward_returns


@pytest.fixture
def synthetic_data():
    return _make_multi_index_data()


@pytest.fixture
def screener():
    return AutoFactorScreen(
        ic_threshold=0.02,
        icir_threshold=0.2,
        ic_positive_ratio=0.50,
        corr_threshold=0.7,
        decay_halflife_min=5,
    )


class TestAutoFactorScreen:
    def test_screen_returns_list(self, screener, synthetic_data):
        fm, fr = synthetic_data
        result = screener.screen(fm, fr)
        assert isinstance(result, list)

    def test_screen_includes_good_factor(self, screener, synthetic_data):
        fm, fr = synthetic_data
        result = screener.screen(fm, fr)
        assert "factor_0" in result, "factor_0 与收益相关, 应通过筛选"

    def test_screen_excludes_noise_factors(self, synthetic_data):
        fm, fr = synthetic_data
        strict = AutoFactorScreen(
            ic_threshold=0.08,
            icir_threshold=0.5,
            ic_positive_ratio=0.60,
            corr_threshold=0.7,
            decay_halflife_min=5,
        )
        result = strict.screen(fm, fr)
        assert len(result) < len(fm.columns), "严格阈值应过滤掉部分噪声因子"

    def test_screen_empty_factor_matrix(self, screener):
        idx = pd.MultiIndex.from_tuples([], names=["trade_date", "stock_code"])
        fm = pd.DataFrame(index=idx)
        fr = pd.Series(dtype=float, index=idx, name="forward_return")
        result = screener.screen(fm, fr)
        assert result == []


class TestStep1ICFilter:
    def test_high_ic_factor_passes(self):
        fm, fr = _make_multi_index_data(n_dates=100, n_stocks=100)
        screener = AutoFactorScreen(
            ic_threshold=0.01,
            icir_threshold=0.1,
            ic_positive_ratio=0.40,
            corr_threshold=0.95,
            decay_halflife_min=1,
        )
        passed = screener._step1_ic_filter(fm, fr, list(fm.columns))
        assert "factor_0" in passed

    def test_very_strict_threshold_rejects_all(self, synthetic_data):
        fm, fr = synthetic_data
        screener = AutoFactorScreen(
            ic_threshold=0.99,
            icir_threshold=10.0,
            ic_positive_ratio=0.99,
            corr_threshold=0.7,
            decay_halflife_min=5,
        )
        passed = screener._step1_ic_filter(fm, fr, list(fm.columns))
        assert len(passed) == 0


class TestStep2DecayFilter:
    def test_non_decaying_passes(self, screener, synthetic_data):
        fm, fr = synthetic_data
        passed = screener._step2_decay_filter(fm, fr, ["factor_0"])
        assert "factor_0" in passed

    def test_short_series_passes_by_default(self, screener):
        fm, fr = _make_multi_index_data(n_dates=5, n_stocks=10)
        passed = screener._step2_decay_filter(fm, fr, ["factor_0"])
        assert "factor_0" in passed


class TestStep3CorrDedup:
    def test_highly_correlated_drops_one(self):
        fm, fr = _make_multi_index_data(n_dates=60, n_stocks=50, n_factors=3)
        fm["factor_dup"] = fm["factor_0"] * 1.01 + 0.001
        screener = AutoFactorScreen(
            ic_threshold=0.01,
            icir_threshold=0.1,
            ic_positive_ratio=0.40,
            corr_threshold=0.7,
            decay_halflife_min=1,
        )
        result = screener._step3_corr_dedup(fm, fr, ["factor_0", "factor_dup"])
        assert len(result) == 1, "高相关因子对应只保留 1 个"

    def test_uncorrelated_keeps_all(self, screener, synthetic_data):
        fm, fr = synthetic_data
        names = ["factor_0", "factor_1", "factor_2"]
        result = screener._step3_corr_dedup(fm, fr, names)
        assert len(result) >= 2


class TestHalflife:
    def test_decaying_series(self):
        t = np.arange(100)
        values = np.exp(-0.03 * t) * 0.1
        series = pd.Series(values)
        hl = AutoFactorScreen._halflife(series)
        assert 15 < hl < 30, f"指数衰减 halflife 应约为 23, 实际 {hl:.1f}"

    def test_non_decaying_series(self):
        series = pd.Series(np.ones(50) * 0.05)
        hl = AutoFactorScreen._halflife(series)
        assert hl == np.inf or hl > 1000

    def test_short_series_returns_nan(self):
        series = pd.Series([0.1, 0.05])
        hl = AutoFactorScreen._halflife(series)
        assert np.isnan(hl)

    def test_increasing_series(self):
        t = np.arange(50)
        values = 0.01 + 0.001 * t
        series = pd.Series(values)
        hl = AutoFactorScreen._halflife(series)
        assert hl == np.inf or hl > 1000
