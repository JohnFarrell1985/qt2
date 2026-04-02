"""Tests for src/factor/factor_calc.py"""
import numpy as np
import pandas as pd
import pytest

from src.factor.factor_calc import (
    calc_momentum,
    calc_volatility,
    calc_turnover_avg,
    calc_volume_ratio,
    calc_rsi,
    calc_macd_histogram,
    calc_amplitude,
    calc_all_technical_factors,
)


@pytest.fixture
def close_series():
    np.random.seed(42)
    prices = 100 + np.cumsum(np.random.randn(120) * 0.5)
    return pd.Series(prices, name="close")


@pytest.fixture
def volume_series():
    np.random.seed(42)
    return pd.Series(np.random.randint(100_000, 1_000_000, size=120).astype(float), name="volume")


@pytest.fixture
def turnover_series():
    np.random.seed(42)
    return pd.Series(np.random.uniform(0.5, 10.0, size=120), name="turnover_rate")


@pytest.fixture
def daily_df(close_series, volume_series, turnover_series):
    np.random.seed(42)
    high = close_series + np.abs(np.random.randn(120)) * 2
    low = close_series - np.abs(np.random.randn(120)) * 2
    return pd.DataFrame({
        "close": close_series.values,
        "high": high.values,
        "low": low.values,
        "volume": volume_series.values,
        "turnover_rate": turnover_series.values,
    })


# ---- calc_momentum ----

class TestCalcMomentum:
    def test_output_length(self, close_series):
        result = calc_momentum(close_series, window=20)
        assert len(result) == len(close_series)

    def test_first_n_values_are_nan(self, close_series):
        result = calc_momentum(close_series, window=20)
        assert result.iloc[:20].isna().all()

    def test_correct_value(self, close_series):
        result = calc_momentum(close_series, window=5)
        expected = (close_series.iloc[5] - close_series.iloc[0]) / close_series.iloc[0]
        assert pytest.approx(result.iloc[5], rel=1e-6) == expected

    def test_custom_window(self, close_series):
        for w in [5, 10, 60]:
            result = calc_momentum(close_series, window=w)
            assert result.iloc[:w].isna().all()
            assert result.iloc[w:].notna().any()

    def test_empty_series(self):
        empty = pd.Series(dtype=float)
        result = calc_momentum(empty)
        assert len(result) == 0

    def test_constant_prices_give_zero_momentum(self):
        s = pd.Series([10.0] * 50)
        result = calc_momentum(s, window=5)
        assert (result.dropna() == 0).all()


# ---- calc_volatility ----

class TestCalcVolatility:
    def test_output_length(self, close_series):
        result = calc_volatility(close_series, window=20)
        assert len(result) == len(close_series)

    def test_non_negative(self, close_series):
        result = calc_volatility(close_series, window=20)
        assert (result.dropna() >= 0).all()

    def test_constant_prices_give_zero_vol(self):
        s = pd.Series([50.0] * 50)
        result = calc_volatility(s, window=10)
        assert (result.dropna() == 0).all()

    def test_leading_nans(self, close_series):
        result = calc_volatility(close_series, window=20)
        assert result.iloc[:20].isna().all()


# ---- calc_turnover_avg ----

class TestCalcTurnoverAvg:
    def test_output_length(self, turnover_series):
        result = calc_turnover_avg(turnover_series, window=20)
        assert len(result) == len(turnover_series)

    def test_leading_nans(self, turnover_series):
        result = calc_turnover_avg(turnover_series, window=20)
        assert result.iloc[:19].isna().all()

    def test_correct_rolling_mean(self, turnover_series):
        result = calc_turnover_avg(turnover_series, window=5)
        expected = turnover_series.iloc[:5].mean()
        assert pytest.approx(result.iloc[4], rel=1e-6) == expected


# ---- calc_volume_ratio ----

class TestCalcVolumeRatio:
    def test_output_length(self, volume_series):
        result = calc_volume_ratio(volume_series, short=5, long=20)
        assert len(result) == len(volume_series)

    def test_ratio_around_one_for_constant(self):
        s = pd.Series([1000.0] * 50)
        result = calc_volume_ratio(s, short=5, long=20)
        valid = result.dropna()
        assert (np.abs(valid - 1.0) < 1e-10).all()

    def test_zero_long_avg_handled(self):
        s = pd.Series([0.0] * 25 + [100.0] * 25)
        result = calc_volume_ratio(s, short=5, long=20)
        assert not np.isinf(result).any()


# ---- calc_rsi ----

class TestCalcRSI:
    def test_output_length(self, close_series):
        result = calc_rsi(close_series, period=14)
        assert len(result) == len(close_series)

    def test_rsi_bounded_0_100(self, close_series):
        result = calc_rsi(close_series, period=14).dropna()
        assert (result >= 0).all() and (result <= 100).all()

    def test_mostly_gains_rsi_high(self):
        np.random.seed(99)
        prices = 100 + np.cumsum(np.abs(np.random.randn(100)) * 0.8 - 0.05)
        s = pd.Series(prices)
        result = calc_rsi(s, period=14).dropna()
        assert len(result) > 0
        assert result.iloc[-1] > 60

    def test_mostly_losses_rsi_low(self):
        np.random.seed(99)
        prices = 100 - np.cumsum(np.abs(np.random.randn(100)) * 0.8 - 0.05)
        s = pd.Series(prices)
        result = calc_rsi(s, period=14).dropna()
        assert len(result) > 0
        assert result.iloc[-1] < 40

    def test_all_gains_returns_nan(self):
        s = pd.Series(np.arange(1, 52, dtype=float))
        result = calc_rsi(s, period=14)
        valid = result.dropna()
        assert len(valid) == 0


# ---- calc_macd_histogram ----

class TestCalcMACDHistogram:
    def test_output_length(self, close_series):
        result = calc_macd_histogram(close_series)
        assert len(result) == len(close_series)

    def test_converges_for_constant_prices(self):
        s = pd.Series([100.0] * 100)
        result = calc_macd_histogram(s)
        assert abs(result.iloc[-1]) < 1e-6

    def test_returns_series(self, close_series):
        result = calc_macd_histogram(close_series)
        assert isinstance(result, pd.Series)


# ---- calc_amplitude ----

class TestCalcAmplitude:
    def test_output_length(self, daily_df):
        result = calc_amplitude(daily_df["high"], daily_df["low"], daily_df["close"], window=20)
        assert len(result) == len(daily_df)

    def test_non_negative(self, daily_df):
        result = calc_amplitude(daily_df["high"], daily_df["low"], daily_df["close"], window=20)
        valid = result.dropna()
        assert (valid >= 0).all()

    def test_zero_amplitude_when_high_equals_low(self):
        n = 50
        close = pd.Series([100.0] * n)
        high = pd.Series([100.0] * n)
        low = pd.Series([100.0] * n)
        result = calc_amplitude(high, low, close, window=5)
        valid = result.dropna()
        assert (valid == 0).all()


# ---- calc_all_technical_factors ----

class TestCalcAllTechnicalFactors:
    def test_adds_momentum_columns(self, daily_df):
        result = calc_all_technical_factors(daily_df)
        for col in ["mom_5", "mom_10", "mom_20", "mom_60"]:
            assert col in result.columns

    def test_adds_volatility_columns(self, daily_df):
        result = calc_all_technical_factors(daily_df)
        assert "vol_20" in result.columns
        assert "vol_60" in result.columns

    def test_adds_rsi_and_macd(self, daily_df):
        result = calc_all_technical_factors(daily_df)
        assert "rsi_14" in result.columns
        assert "macd_hist" in result.columns

    def test_adds_volume_ratio(self, daily_df):
        result = calc_all_technical_factors(daily_df)
        assert "volume_ratio" in result.columns

    def test_adds_turnover_avg(self, daily_df):
        result = calc_all_technical_factors(daily_df)
        assert "turnover_avg_20" in result.columns

    def test_adds_amplitude(self, daily_df):
        result = calc_all_technical_factors(daily_df)
        assert "amplitude_20" in result.columns

    def test_preserves_original_columns(self, daily_df):
        result = calc_all_technical_factors(daily_df)
        for col in ["close", "high", "low", "volume", "turnover_rate"]:
            assert col in result.columns

    def test_does_not_modify_input(self, daily_df):
        original_cols = set(daily_df.columns)
        calc_all_technical_factors(daily_df)
        assert set(daily_df.columns) == original_cols

    def test_without_volume_column(self):
        df = pd.DataFrame({"close": [100.0] * 30, "high": [101.0] * 30, "low": [99.0] * 30})
        result = calc_all_technical_factors(df)
        assert "volume_ratio" not in result.columns

    def test_without_turnover_column(self):
        df = pd.DataFrame({
            "close": [100.0] * 30,
            "high": [101.0] * 30,
            "low": [99.0] * 30,
            "volume": [1000.0] * 30,
        })
        result = calc_all_technical_factors(df)
        assert "turnover_avg_20" not in result.columns

    def test_without_high_low_columns(self):
        df = pd.DataFrame({"close": [100.0] * 30, "volume": [1000.0] * 30})
        result = calc_all_technical_factors(df)
        assert "amplitude_20" not in result.columns

    def test_output_same_length(self, daily_df):
        result = calc_all_technical_factors(daily_df)
        assert len(result) == len(daily_df)
