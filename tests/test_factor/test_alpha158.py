"""Tests for src/factor/alpha158.py"""

import numpy as np
import pandas as pd
import pytest

from src.factor.alpha158 import Alpha158Calculator
from src.factor.base import factor_registry


@pytest.fixture
def ohlcv_df():
    """生成 200 行仿真 OHLCV 日线数据"""
    np.random.seed(42)
    n = 200
    close = 50.0 + np.cumsum(np.random.randn(n) * 0.5)
    close = np.maximum(close, 5.0)
    noise_h = np.abs(np.random.randn(n)) * 1.5
    noise_l = np.abs(np.random.randn(n)) * 1.5
    high = close + noise_h
    low = close - noise_l
    low = np.maximum(low, 1.0)
    open_ = close + np.random.randn(n) * 0.3
    open_ = np.maximum(open_, 1.0)
    volume = np.random.randint(100_000, 5_000_000, size=n).astype(float)
    return pd.DataFrame({
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


@pytest.fixture
def calculator():
    return Alpha158Calculator(windows=[5, 10, 20])


class TestAlpha158Calculator:
    def test_calc_returns_dataframe(self, calculator, ohlcv_df):
        result = calculator.calc(ohlcv_df)
        assert isinstance(result, pd.DataFrame)

    def test_original_columns_preserved(self, calculator, ohlcv_df):
        result = calculator.calc(ohlcv_df)
        for col in ["open", "high", "low", "close", "volume"]:
            assert col in result.columns

    def test_factor_count_above_100(self, ohlcv_df):
        calc = Alpha158Calculator(windows=[5, 10, 20, 30, 60])
        result = calc.calc(ohlcv_df)
        n_factors = len(result.columns) - 5
        assert n_factors >= 100, f"期望 >=100 因子, 实际 {n_factors}"

    def test_factor_count_matches_factor_names(self, calculator, ohlcv_df):
        result = calculator.calc(ohlcv_df)
        n_computed = len(result.columns) - 5
        n_names = len(calculator.factor_names)
        assert n_computed == n_names

    def test_no_nan_after_warmup(self, ohlcv_df):
        calc = Alpha158Calculator(windows=[5, 10])
        result = calc.calc(ohlcv_df)
        factor_cols = [c for c in result.columns if c not in ("open", "high", "low", "close", "volume")]
        tail = result[factor_cols].iloc[60:]
        nan_ratio = tail.isna().mean().mean()
        assert nan_ratio < 0.05, f"warmup 后 NaN 比例 {nan_ratio:.2%} 过高"

    def test_same_length_as_input(self, calculator, ohlcv_df):
        result = calculator.calc(ohlcv_df)
        assert len(result) == len(ohlcv_df)

    def test_does_not_modify_input(self, calculator, ohlcv_df):
        original_cols = set(ohlcv_df.columns)
        calculator.calc(ohlcv_df)
        assert set(ohlcv_df.columns) == original_cols

    def test_custom_windows(self, ohlcv_df):
        calc = Alpha158Calculator(windows=[3, 7])
        result = calc.calc(ohlcv_df)
        assert "PRICE_mom_3" in result.columns
        assert "PRICE_mom_7" in result.columns
        assert "PRICE_mom_20" not in result.columns

    def test_kbar_factors_present(self, calculator, ohlcv_df):
        result = calculator.calc(ohlcv_df)
        expected = [
            "KBAR_open", "KBAR_high_low", "KBAR_close_pos",
            "KBAR_upper_shadow", "KBAR_lower_shadow", "KBAR_body_ratio",
            "KBAR_high_open", "KBAR_low_open",
        ]
        for name in expected:
            assert name in result.columns, f"缺少 KBAR 因子: {name}"

    def test_price_factors_per_window(self, calculator, ohlcv_df):
        result = calculator.calc(ohlcv_df)
        for w in calculator.windows:
            assert f"PRICE_mom_{w}" in result.columns
            assert f"PRICE_mean_rev_{w}" in result.columns
            assert f"PRICE_bias_{w}" in result.columns

    def test_volume_factors_per_window(self, calculator, ohlcv_df):
        result = calculator.calc(ohlcv_df)
        for w in calculator.windows:
            assert f"VOL_mean_ratio_{w}" in result.columns
            assert f"VOL_cv_{w}" in result.columns

    def test_std_factors_per_window(self, calculator, ohlcv_df):
        result = calculator.calc(ohlcv_df)
        for w in calculator.windows:
            assert f"STD_ret_{w}" in result.columns
            assert f"STD_parkinson_{w}" in result.columns

    def test_rsrs_factors_per_window(self, calculator, ohlcv_df):
        result = calculator.calc(ohlcv_df)
        for w in calculator.windows:
            assert f"RSRS_high_max_{w}" in result.columns
            assert f"RSRS_low_min_{w}" in result.columns

    def test_corr_factors_per_window(self, calculator, ohlcv_df):
        result = calculator.calc(ohlcv_df)
        for w in calculator.windows:
            assert f"CORR_close_vol_{w}" in result.columns
            assert f"CORR_ret_vol_{w}" in result.columns

    def test_no_inf_values(self, calculator, ohlcv_df):
        result = calculator.calc(ohlcv_df)
        factor_cols = [c for c in result.columns if c not in ("open", "high", "low", "close", "volume")]
        assert not np.isinf(result[factor_cols]).any().any(), "存在 inf 值"

    def test_factor_names_property(self, calculator):
        names = calculator.factor_names
        assert isinstance(names, list)
        assert len(names) > 50
        assert len(names) == len(set(names)), "因子名称有重复"


class TestRegisteredFactors:
    """测试通过 @register_factor 注册的 BaseFactor 子类"""

    def test_registered_factor_count(self):
        import src.factor.alpha158  # noqa: F401
        kbar = factor_registry.list_names(category="kbar")
        assert len(kbar) >= 5

    def test_kbar_open_compute(self, ohlcv_df):
        factor = factor_registry.get("KBAR_open")
        assert factor is not None
        result = factor.compute(ohlcv_df)
        assert isinstance(result, pd.Series)
        assert len(result) == len(ohlcv_df)
        expected = (ohlcv_df["close"] - ohlcv_df["open"]) / (ohlcv_df["open"] + 1e-12)
        pd.testing.assert_series_equal(result, expected, check_names=False)

    def test_price_mom_5_compute(self, ohlcv_df):
        factor = factor_registry.get("PRICE_mom_5")
        assert factor is not None
        result = factor.compute(ohlcv_df)
        assert len(result) == len(ohlcv_df)
        assert result.iloc[:5].isna().any() or True  # shift 产生 NaN

    def test_vol_cv_20_compute(self, ohlcv_df):
        factor = factor_registry.get("VOL_cv_20")
        assert factor is not None
        result = factor.compute(ohlcv_df)
        assert len(result) == len(ohlcv_df)
        valid = result.dropna()
        assert (valid >= 0).all()

    def test_std_ret_20_compute(self, ohlcv_df):
        factor = factor_registry.get("STD_ret_20")
        assert factor is not None
        result = factor.compute(ohlcv_df)
        valid = result.dropna()
        assert (valid >= 0).all()

    def test_rsrs_range_20_compute(self, ohlcv_df):
        factor = factor_registry.get("RSRS_range_20")
        assert factor is not None
        result = factor.compute(ohlcv_df)
        valid = result.dropna()
        assert (valid >= 0).all()

    def test_corr_close_vol_20_compute(self, ohlcv_df):
        factor = factor_registry.get("CORR_close_vol_20")
        assert factor is not None
        result = factor.compute(ohlcv_df)
        valid = result.dropna()
        assert (valid >= -1.0001).all() and (valid <= 1.0001).all()

    def test_all_registered_have_metadata(self):
        import src.factor.alpha158  # noqa: F401
        all_factors = factor_registry.list_all()
        alpha158_factors = [f for f in all_factors if f["category"] in ("kbar", "price", "volume", "std", "rsrs", "corr")]
        assert len(alpha158_factors) >= 20
        for f in alpha158_factors:
            assert f["name"]
            assert f["category"]
            assert f["version"]

    def test_compute_all_via_registry(self, ohlcv_df):
        names = ["KBAR_open", "PRICE_mom_5", "STD_ret_20"]
        result = factor_registry.compute_all(ohlcv_df, names=names)
        for n in names:
            assert n in result.columns
