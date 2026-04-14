"""E2E: Alpha158 因子计算 — 真实 stock_daily 数据

覆盖:
  P1-21 Alpha158Calculator.calc + factor_names + BaseFactor registry compute
"""
import pandas as pd
import pytest

from src.factor.alpha158 import Alpha158Calculator
from src.factor.base import factor_registry


class TestAlpha158CalculatorE2E:
    """Alpha158 计算器 — 真实单股日线"""

    def test_calc_produces_factor_columns(self, real_single_stock_ohlcv):
        calc = Alpha158Calculator(windows=[5, 10, 20])
        result = calc.calc(real_single_stock_ohlcv)
        assert isinstance(result, pd.DataFrame)
        assert result.shape[0] == real_single_stock_ohlcv.shape[0]
        original_cols = set(real_single_stock_ohlcv.columns)
        new_cols = set(result.columns) - original_cols
        assert len(new_cols) > 50, f"应新增 50+ 因子列, 实际 {len(new_cols)}"

    def test_factor_names_match_calc_output(self, real_single_stock_ohlcv):
        calc = Alpha158Calculator(windows=[5, 20])
        names = calc.factor_names
        result = calc.calc(real_single_stock_ohlcv)
        for name in names:
            assert name in result.columns, f"factor_names 中 {name} 不在 calc 输出中"

    def test_kbar_factors_are_bounded(self, real_single_stock_ohlcv):
        calc = Alpha158Calculator(windows=[5])
        result = calc.calc(real_single_stock_ohlcv)
        for col in ["KBAR_close_pos", "KBAR_upper_shadow", "KBAR_lower_shadow"]:
            if col in result.columns:
                vals = result[col].dropna()
                assert vals.between(-5, 5).all(), f"{col} 有异常值"

    def test_price_momentum_factors_nonzero(self, real_single_stock_ohlcv):
        calc = Alpha158Calculator(windows=[20])
        result = calc.calc(real_single_stock_ohlcv)
        mom20 = result["PRICE_mom_20"].dropna()
        assert len(mom20) > 100, "应有足够的非 NaN 动量值"
        assert (mom20 != 0).sum() > 50, "动量不应全为 0"

    def test_volume_factors_positive_ratios(self, real_single_stock_ohlcv):
        calc = Alpha158Calculator(windows=[10])
        result = calc.calc(real_single_stock_ohlcv)
        vol_ratio = result["VOL_mean_ratio_10"].dropna()
        assert (vol_ratio > 0).all(), "量比应为正"

    def test_std_factors_nonnegative(self, real_single_stock_ohlcv):
        calc = Alpha158Calculator(windows=[20])
        result = calc.calc(real_single_stock_ohlcv)
        std_ret = result["STD_ret_20"].dropna()
        assert (std_ret >= 0).all(), "收益率标准差应非负"

    def test_correlation_factors_bounded(self, real_single_stock_ohlcv):
        calc = Alpha158Calculator(windows=[20])
        result = calc.calc(real_single_stock_ohlcv)
        corr_col = "CORR_close_vol_20"
        if corr_col in result.columns:
            vals = result[corr_col].dropna()
            assert (vals.between(-1.01, 1.01)).all(), "相关系数应在 [-1, 1]"

    def test_no_all_nan_factors(self, real_single_stock_ohlcv):
        calc = Alpha158Calculator(windows=[5, 20])
        result = calc.calc(real_single_stock_ohlcv)
        for name in calc.factor_names:
            series = result[name]
            non_nan = series.dropna()
            assert len(non_nan) > 0, f"因子 {name} 全为 NaN"

    def test_default_windows_from_config(self, real_single_stock_ohlcv):
        calc = Alpha158Calculator()
        assert len(calc.windows) >= 3
        result = calc.calc(real_single_stock_ohlcv)
        assert result.shape[1] > real_single_stock_ohlcv.shape[1] + 100


class TestRegisteredFactorsE2E:
    """通过 FactorRegistry 注册的 BaseFactor 子类 — 真实数据 compute"""

    @pytest.fixture
    def factor_names(self):
        return [
            "KBAR_open", "KBAR_high_low", "KBAR_close_pos",
            "PRICE_mom_5", "PRICE_mom_20", "PRICE_mean_rev_20",
            "VOL_mean_ratio_5", "VOL_cv_20",
            "STD_ret_5", "STD_ret_20",
            "RSRS_high_max_20", "RSRS_range_20",
            "CORR_close_vol_20", "CORR_ret_vol_20",
        ]

    def test_registered_factors_compute_on_real_data(
        self, real_single_stock_ohlcv, factor_names,
    ):
        for name in factor_names:
            factor = factor_registry.get(name)
            if factor is None:
                continue
            result = factor.compute(real_single_stock_ohlcv)
            assert isinstance(result, pd.Series)
            assert len(result) == len(real_single_stock_ohlcv)
            non_nan = result.dropna()
            assert len(non_nan) > 0, f"因子 {name} compute 全 NaN"

    def test_registry_has_expected_count(self):
        all_factors = factor_registry.list_all()
        assert len(all_factors) >= 20, f"预期 20+ 注册因子, 实际 {len(all_factors)}"

    def test_compute_all_on_real_data(self, real_single_stock_ohlcv):
        result_df = factor_registry.compute_all(real_single_stock_ohlcv)
        assert isinstance(result_df, pd.DataFrame)
        new_cols = set(result_df.columns) - set(real_single_stock_ohlcv.columns)
        assert len(new_cols) >= 15, f"compute_all 应新增 15+ 列, 实际 {len(new_cols)}"
