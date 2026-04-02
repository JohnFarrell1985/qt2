"""Tests for src/factor/factor_analysis.py"""
import numpy as np
import pandas as pd
import pytest

from src.factor.factor_analysis import (
    calc_ic,
    calc_ic_series,
    calc_icir,
    group_return_test,
    single_factor_report,
)


# ---- calc_ic ----

class TestCalcIC:
    def test_perfect_positive_correlation(self):
        fv = pd.Series(range(50), dtype=float)
        fr = pd.Series(range(50), dtype=float)
        ic = calc_ic(fv, fr)
        assert pytest.approx(ic, abs=1e-6) == 1.0

    def test_perfect_negative_correlation(self):
        fv = pd.Series(range(50), dtype=float)
        fr = pd.Series(range(49, -1, -1), dtype=float)
        ic = calc_ic(fv, fr)
        assert pytest.approx(ic, abs=1e-6) == -1.0

    def test_too_few_valid_returns_nan(self):
        fv = pd.Series([1.0, 2.0, 3.0])
        fr = pd.Series([0.01, 0.02, 0.03])
        ic = calc_ic(fv, fr)
        assert np.isnan(ic)

    def test_with_nan_values(self):
        fv = pd.Series([np.nan] + list(range(1, 51)), dtype=float)
        fr = pd.Series([np.nan] + list(range(1, 51)), dtype=float)
        ic = calc_ic(fv, fr)
        assert pytest.approx(ic, abs=1e-6) == 1.0

    def test_returns_float(self):
        np.random.seed(0)
        fv = pd.Series(np.random.randn(100))
        fr = pd.Series(np.random.randn(100))
        ic = calc_ic(fv, fr)
        assert isinstance(ic, float)

    def test_ic_bounded(self):
        np.random.seed(0)
        fv = pd.Series(np.random.randn(100))
        fr = pd.Series(np.random.randn(100))
        ic = calc_ic(fv, fr)
        assert -1.0 <= ic <= 1.0


# ---- calc_ic_series ----

class TestCalcICSeries:
    @pytest.fixture
    def multi_index_data(self):
        np.random.seed(0)
        dates = pd.date_range("2025-01-01", periods=5, freq="D")
        codes = [f"S{i:04d}" for i in range(30)]
        idx = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])
        factor_df = pd.DataFrame(
            {"factor_a": np.random.randn(len(idx))}, index=idx
        )
        return_df = pd.DataFrame(
            {"forward_return": np.random.randn(len(idx))}, index=idx
        )
        return factor_df, return_df

    def test_returns_series(self, multi_index_data):
        factor_df, return_df = multi_index_data
        result = calc_ic_series(factor_df, return_df, "factor_a")
        assert isinstance(result, pd.Series)

    def test_length_matches_dates(self, multi_index_data):
        factor_df, return_df = multi_index_data
        result = calc_ic_series(factor_df, return_df, "factor_a")
        assert len(result) == 5

    def test_values_bounded(self, multi_index_data):
        factor_df, return_df = multi_index_data
        result = calc_ic_series(factor_df, return_df, "factor_a")
        assert (result.dropna().abs() <= 1.0).all()

    def test_too_few_stocks_per_date_skipped(self):
        dates = pd.date_range("2025-01-01", periods=3, freq="D")
        codes = ["S0001", "S0002"]
        idx = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])
        factor_df = pd.DataFrame({"f": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]}, index=idx)
        return_df = pd.DataFrame({"forward_return": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6]}, index=idx)
        result = calc_ic_series(factor_df, return_df, "f")
        assert len(result) == 0

    def test_missing_factor_col_handled(self, multi_index_data):
        factor_df, return_df = multi_index_data
        result = calc_ic_series(factor_df, return_df, "nonexistent")
        assert len(result) == 0


# ---- calc_icir ----

class TestCalcICIR:
    def test_positive_icir(self):
        ic = pd.Series([0.05, 0.06, 0.04, 0.07, 0.05])
        result = calc_icir(ic)
        assert result > 0

    def test_negative_icir(self):
        ic = pd.Series([-0.05, -0.06, -0.04, -0.07, -0.05])
        result = calc_icir(ic)
        assert result < 0

    def test_zero_std_returns_zero(self):
        ic = pd.Series([0.05, 0.05, 0.05, 0.05])
        if ic.std() == 0:
            assert calc_icir(ic) == 0.0
        else:
            result = calc_icir(ic)
            assert isinstance(result, float)

    def test_formula(self):
        ic = pd.Series([0.1, 0.2, 0.3])
        expected = ic.mean() / ic.std()
        assert pytest.approx(calc_icir(ic), rel=1e-6) == expected

    def test_single_value(self):
        ic = pd.Series([0.05])
        result = calc_icir(ic)
        assert isinstance(result, float)


# ---- group_return_test ----

class TestGroupReturnTest:
    def test_returns_dict(self):
        np.random.seed(0)
        fv = pd.Series(np.random.randn(100))
        fr = pd.Series(np.random.randn(100))
        result = group_return_test(fv, fr, n_groups=5)
        assert isinstance(result, dict)

    def test_correct_group_count(self):
        np.random.seed(0)
        fv = pd.Series(np.random.randn(100))
        fr = pd.Series(np.random.randn(100))
        result = group_return_test(fv, fr, n_groups=5)
        for i in range(1, 6):
            assert f"G{i}" in result

    def test_long_short_present(self):
        np.random.seed(0)
        fv = pd.Series(np.random.randn(100))
        fr = pd.Series(np.random.randn(100))
        result = group_return_test(fv, fr, n_groups=5)
        assert "long_short" in result
        assert pytest.approx(result["long_short"], abs=1e-10) == result["G5"] - result["G1"]

    def test_too_few_data_returns_empty(self):
        fv = pd.Series([1.0, 2.0])
        fr = pd.Series([0.01, 0.02])
        result = group_return_test(fv, fr, n_groups=5)
        assert result == {}

    def test_with_nan_values(self):
        np.random.seed(0)
        fv = pd.Series([np.nan] * 10 + list(np.random.randn(100)))
        fr = pd.Series([np.nan] * 10 + list(np.random.randn(100)))
        result = group_return_test(fv, fr, n_groups=5)
        assert "G1" in result

    def test_three_groups(self):
        np.random.seed(0)
        fv = pd.Series(np.random.randn(60))
        fr = pd.Series(np.random.randn(60))
        result = group_return_test(fv, fr, n_groups=3)
        assert "G1" in result and "G3" in result
        assert "long_short" in result


# ---- single_factor_report ----

class TestSingleFactorReport:
    def test_report_structure(self):
        ic = pd.Series([0.05, 0.06, 0.04, 0.07, 0.03])
        gr = {"G1": -0.01, "G5": 0.02, "long_short": 0.03}
        report = single_factor_report("mom_20", ic, gr)
        assert report["factor_name"] == "mom_20"
        assert "ic_mean" in report
        assert "ic_std" in report
        assert "icir" in report
        assert "ic_positive_ratio" in report
        assert "group_returns" in report
        assert "n_periods" in report
        assert "effective" in report

    def test_effective_flag_true(self):
        ic = pd.Series([0.05, 0.06, 0.04, 0.07, 0.03])
        gr = {}
        report = single_factor_report("good_factor", ic, gr)
        assert report["effective"] == True

    def test_effective_flag_false(self):
        ic = pd.Series([0.001, -0.001, 0.002, -0.002, 0.001])
        gr = {}
        report = single_factor_report("weak_factor", ic, gr)
        assert report["effective"] == False

    def test_empty_ic_series(self):
        ic = pd.Series(dtype=float)
        gr = {}
        report = single_factor_report("empty", ic, gr)
        assert report["ic_mean"] is None
        assert report["ic_std"] is None
        assert report["icir"] is None
        assert report["ic_positive_ratio"] is None
        assert report["n_periods"] == 0
        assert report["effective"] is False

    def test_ic_positive_ratio(self):
        ic = pd.Series([0.1, 0.2, -0.1, 0.3, -0.05])
        gr = {}
        report = single_factor_report("test", ic, gr)
        assert report["ic_positive_ratio"] == round(3 / 5, 4)

    def test_n_periods(self):
        ic = pd.Series([0.1] * 12)
        report = single_factor_report("test", ic, {})
        assert report["n_periods"] == 12
