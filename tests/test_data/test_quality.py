"""Tests for src/data/quality.py and src/data/schemas.py"""
import numpy as np
import pandas as pd
import pytest

from src.data.quality import DataQualityChecker


@pytest.fixture
def checker():
    return DataQualityChecker(z_threshold=3.0, max_pct_change=22.0)


@pytest.fixture
def valid_stock_df():
    dates = pd.date_range("2025-01-06", periods=10, freq="B")
    return pd.DataFrame({
        "code": ["600000"] * 10,
        "trade_date": dates,
        "open": [10.0 + i * 0.1 for i in range(10)],
        "high": [10.5 + i * 0.1 for i in range(10)],
        "low": [9.5 + i * 0.1 for i in range(10)],
        "close": [10.2 + i * 0.1 for i in range(10)],
        "volume": [1000.0 + i * 100 for i in range(10)],
    })


@pytest.fixture
def invalid_stock_df():
    dates = pd.date_range("2025-01-06", periods=3, freq="B")
    return pd.DataFrame({
        "code": ["600000"] * 3,
        "trade_date": dates,
        "open": [10.0, -5.0, 10.0],
        "high": [10.5, 10.5, 10.5],
        "low": [9.5, 9.5, 9.5],
        "close": [10.2, 10.2, 10.2],
        "volume": [1000.0, 1000.0, 1000.0],
    })


# ---- validate_schema ----

class TestValidateSchema:
    def test_valid_data(self, checker, valid_stock_df):
        result = checker.validate_schema(valid_stock_df, "stock_daily")
        assert result["valid"] is True
        assert result["errors"] == []

    def test_invalid_data_negative_open(self, checker, invalid_stock_df):
        result = checker.validate_schema(invalid_stock_df, "stock_daily")
        assert result["valid"] is False
        assert len(result["errors"]) > 0

    def test_unknown_schema(self, checker, valid_stock_df):
        result = checker.validate_schema(valid_stock_df, "nonexistent")
        assert result["valid"] is False
        assert "Unknown schema" in result["errors"][0]

    def test_high_less_than_low(self, checker):
        dates = pd.date_range("2025-01-06", periods=2, freq="B")
        df = pd.DataFrame({
            "code": ["600000"] * 2,
            "trade_date": dates,
            "open": [10.0, 10.0],
            "high": [8.0, 10.5],
            "low": [9.5, 9.5],
            "close": [10.0, 10.0],
            "volume": [1000.0, 1000.0],
        })
        result = checker.validate_schema(df, "stock_daily")
        assert result["valid"] is False

    def test_etf_schema(self, checker, valid_stock_df):
        result = checker.validate_schema(valid_stock_df, "etf_daily")
        assert result["valid"] is True

    def test_cb_schema(self, checker):
        dates = pd.date_range("2025-01-06", periods=3, freq="B")
        df = pd.DataFrame({
            "code": ["127000"] * 3,
            "trade_date": dates,
            "close": [100.0, 101.0, 102.0],
            "volume": [500.0, 600.0, 700.0],
        })
        result = checker.validate_schema(df, "cb_data")
        assert result["valid"] is True


# ---- check_continuity ----

class TestCheckContinuity:
    def test_no_gaps(self, checker, valid_stock_df):
        gaps = checker.check_continuity(valid_stock_df)
        assert gaps == []

    def test_with_gap(self, checker):
        dates = pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-20", "2025-01-21"])
        df = pd.DataFrame({"trade_date": dates})
        gaps = checker.check_continuity(df)
        assert len(gaps) == 1
        assert gaps[0]["gap_days"] == 13

    def test_empty_df(self, checker):
        df = pd.DataFrame(columns=["trade_date"])
        gaps = checker.check_continuity(df)
        assert gaps == []

    def test_single_row(self, checker):
        df = pd.DataFrame({"trade_date": pd.to_datetime(["2025-01-06"])})
        gaps = checker.check_continuity(df)
        assert gaps == []

    def test_missing_column(self, checker):
        df = pd.DataFrame({"date": [1, 2, 3]})
        gaps = checker.check_continuity(df)
        assert gaps == []


# ---- detect_anomalies ----

class TestDetectAnomalies:
    def test_no_anomalies(self, checker):
        df = pd.DataFrame({"value": np.random.normal(100, 1, 100)})
        idx = checker.detect_anomalies(df, "value")
        assert len(idx) == 0 or len(idx) < 5

    def test_known_outlier(self, checker):
        values = [10.0] * 100
        values[50] = 10000.0
        df = pd.DataFrame({"value": values})
        idx = checker.detect_anomalies(df, "value")
        assert 50 in idx

    def test_missing_column(self, checker):
        df = pd.DataFrame({"other": [1, 2, 3]})
        idx = checker.detect_anomalies(df, "value")
        assert len(idx) == 0

    def test_constant_series(self, checker):
        df = pd.DataFrame({"value": [5.0] * 20})
        idx = checker.detect_anomalies(df, "value")
        assert len(idx) == 0

    def test_custom_threshold(self, checker):
        values = list(np.random.normal(0, 1, 200))
        values.append(5.0)
        df = pd.DataFrame({"value": values})
        idx_strict = checker.detect_anomalies(df, "value", z_threshold=2.0)
        idx_loose = checker.detect_anomalies(df, "value", z_threshold=10.0)
        assert len(idx_strict) >= len(idx_loose)


# ---- full_check ----

class TestFullCheck:
    def test_all_pass(self, checker, valid_stock_df):
        result = checker.full_check(valid_stock_df, "stock_daily")
        assert result["schema"]["valid"] is True
        assert isinstance(result["gaps"], list)
        assert isinstance(result["anomalies"], dict)

    def test_returns_all_keys(self, checker, valid_stock_df):
        result = checker.full_check(valid_stock_df)
        assert "schema" in result
        assert "gaps" in result
        assert "anomalies" in result

    def test_invalid_data_detected(self, checker, invalid_stock_df):
        result = checker.full_check(invalid_stock_df, "stock_daily")
        assert result["schema"]["valid"] is False
