"""Tests for src/factor/factor_preprocess.py"""
import numpy as np
import pandas as pd
import pytest

from src.factor.factor_preprocess import (
    winsorize,
    standardize,
    neutralize,
    preprocess_cross_section,
)


@pytest.fixture
def normal_series():
    np.random.seed(0)
    return pd.Series(np.random.randn(200))


@pytest.fixture
def series_with_outliers():
    np.random.seed(0)
    data = np.random.randn(200)
    data[0] = 100.0
    data[1] = -100.0
    return pd.Series(data)


# ---- winsorize ----

class TestWinsorize:
    def test_clips_upper_outlier(self, series_with_outliers):
        result = winsorize(series_with_outliers, n_std=3.0)
        assert result.max() < 100.0

    def test_clips_lower_outlier(self, series_with_outliers):
        result = winsorize(series_with_outliers, n_std=3.0)
        assert result.min() > -100.0

    def test_no_change_within_bounds(self, normal_series):
        result = winsorize(normal_series, n_std=10.0)
        pd.testing.assert_series_equal(result, normal_series)

    def test_output_length_unchanged(self, series_with_outliers):
        result = winsorize(series_with_outliers)
        assert len(result) == len(series_with_outliers)

    def test_stricter_std_clips_more(self, series_with_outliers):
        r_strict = winsorize(series_with_outliers, n_std=1.0)
        r_loose = winsorize(series_with_outliers, n_std=5.0)
        assert r_strict.max() <= r_loose.max()
        assert r_strict.min() >= r_loose.min()

    def test_constant_series(self):
        s = pd.Series([5.0] * 50)
        result = winsorize(s)
        assert (result == 5.0).all()

    def test_single_element(self):
        s = pd.Series([42.0])
        result = winsorize(s)
        assert result.iloc[0] == 42.0


# ---- standardize ----

class TestStandardize:
    def test_mean_near_zero(self, normal_series):
        result = standardize(normal_series)
        assert abs(result.mean()) < 1e-10

    def test_std_near_one(self, normal_series):
        result = standardize(normal_series)
        assert abs(result.std() - 1.0) < 1e-10

    def test_zero_std_returns_zeros(self):
        s = pd.Series([7.0] * 50)
        result = standardize(s)
        assert (result == 0).all()

    def test_nan_std_returns_zeros(self):
        s = pd.Series([np.nan])
        result = standardize(s)
        assert result.isna().all() or (result == 0).all()

    def test_two_elements(self):
        s = pd.Series([0.0, 10.0])
        result = standardize(s)
        assert abs(result.mean()) < 1e-10

    def test_output_length(self, normal_series):
        result = standardize(normal_series)
        assert len(result) == len(normal_series)


# ---- neutralize ----

class TestNeutralize:
    def test_residuals_same_length(self):
        np.random.seed(1)
        n = 50
        factor = pd.Series(np.random.randn(n))
        industry = pd.Series(np.random.choice(["A", "B", "C"], n))
        result = neutralize(factor, industry)
        assert len(result) == n

    def test_with_market_cap(self):
        np.random.seed(1)
        n = 50
        factor = pd.Series(np.random.randn(n))
        industry = pd.Series(np.random.choice(["X", "Y"], n))
        mktcap = pd.Series(np.random.uniform(1e8, 1e10, n))
        result = neutralize(factor, industry, market_cap=mktcap)
        assert len(result) == n

    def test_too_few_valid_returns_original(self):
        factor = pd.Series([1.0, 2.0, np.nan, np.nan, np.nan])
        industry = pd.Series(["A", "B", "A", "B", "A"])
        result = neutralize(factor, industry)
        pd.testing.assert_series_equal(result, factor)

    def test_residuals_mean_near_zero(self):
        np.random.seed(2)
        n = 200
        factor = pd.Series(np.random.randn(n))
        industry = pd.Series(np.random.choice(["A", "B", "C"], n))
        result = neutralize(factor, industry)
        assert abs(result.mean()) < 0.3

    def test_single_industry_raises_or_returns(self):
        np.random.seed(3)
        n = 50
        factor = pd.Series(np.random.randn(n))
        industry = pd.Series(["A"] * n)
        try:
            result = neutralize(factor, industry)
            assert len(result) == n
        except ValueError:
            pass

    def test_two_industries(self):
        np.random.seed(3)
        n = 50
        factor = pd.Series(np.random.randn(n))
        industry = pd.Series(["A"] * 25 + ["B"] * 25)
        result = neutralize(factor, industry)
        assert len(result) == n

    def test_market_cap_with_zeros_clipped(self):
        np.random.seed(4)
        n = 30
        factor = pd.Series(np.random.randn(n))
        industry = pd.Series(np.random.choice(["A", "B"], n))
        mktcap = pd.Series([0.0] * n)
        result = neutralize(factor, industry, market_cap=mktcap)
        assert len(result) == n
        assert result.notna().all()


# ---- preprocess_cross_section ----

class TestPreprocessCrossSection:
    def test_output_shape(self):
        np.random.seed(0)
        df = pd.DataFrame({
            "f1": np.random.randn(100),
            "f2": np.random.randn(100),
        })
        result = preprocess_cross_section(df)
        assert result.shape == df.shape

    def test_standardized_output(self):
        np.random.seed(0)
        df = pd.DataFrame({"f1": np.random.randn(100)})
        result = preprocess_cross_section(df)
        col = result["f1"].dropna()
        assert abs(col.mean()) < 1e-10
        assert abs(col.std() - 1.0) < 0.1

    def test_outliers_clipped(self):
        data = np.zeros(100)
        data[0] = 1000.0
        df = pd.DataFrame({"f1": data})
        result = preprocess_cross_section(df)
        assert result["f1"].max() < 1000.0

    def test_skips_columns_with_few_values(self):
        df = pd.DataFrame({
            "f1": [1.0, 2.0, np.nan, np.nan, np.nan],
            "f2": [10.0, 20.0, 30.0, 40.0, 50.0],
        })
        result = preprocess_cross_section(df)
        assert result["f1"].iloc[0] == 1.0
        assert result["f1"].iloc[1] == 2.0

    def test_does_not_modify_input(self):
        np.random.seed(0)
        df = pd.DataFrame({"f1": np.random.randn(50)})
        original = df.copy()
        preprocess_cross_section(df)
        pd.testing.assert_frame_equal(df, original)

    def test_custom_winsorize_std(self):
        np.random.seed(0)
        data = np.random.randn(100)
        data[0] = 50.0
        df = pd.DataFrame({"f1": data})
        r_strict = preprocess_cross_section(df, winsorize_std=1.0)
        r_loose = preprocess_cross_section(df, winsorize_std=5.0)
        assert r_strict["f1"].max() <= r_loose["f1"].max()

    def test_all_nan_column(self):
        df = pd.DataFrame({"f1": [np.nan] * 20})
        result = preprocess_cross_section(df)
        assert result["f1"].isna().all()

    def test_empty_dataframe(self):
        df = pd.DataFrame()
        result = preprocess_cross_section(df)
        assert result.empty
