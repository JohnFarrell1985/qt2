"""Tests for src/datacollect/validator.py"""
from __future__ import annotations

import pandas as pd
import pytest

from src.datacollect.validator import DataValidator


@pytest.fixture
def validator() -> DataValidator:
    return DataValidator()


# ====================================================================
# Schema checks
# ====================================================================

class TestSchemaValidation:

    def test_empty_dataframe_invalid(self, validator: DataValidator):
        result = validator.validate(pd.DataFrame(), "stock_daily")
        assert not result.is_valid
        assert any(e.level == "schema" for e in result.errors)

    def test_none_dataframe_invalid(self, validator: DataValidator):
        result = validator.validate(None, "stock_daily")
        assert not result.is_valid

    def test_missing_required_column(self, validator: DataValidator):
        df = pd.DataFrame({"code": ["000001.SZ"], "trade_date": ["2024-01-02"]})
        result = validator.validate(df, "stock_daily")
        assert not result.is_valid
        missing = [e for e in result.errors if e.level == "schema" and "missing" in e.message]
        assert len(missing) > 0

    def test_valid_stock_daily_passes_schema(self, validator: DataValidator):
        df = pd.DataFrame({
            "code": ["000001.SZ"],
            "trade_date": ["2024-01-02"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "volume": [100000],
        })
        result = validator.validate(df, "stock_daily")
        schema_errors = [e for e in result.errors if e.level == "schema"]
        assert len(schema_errors) == 0

    def test_non_numeric_column_flagged(self, validator: DataValidator):
        df = pd.DataFrame({
            "code": ["000001.SZ"],
            "trade_date": ["2024-01-02"],
            "open": ["abc"],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "volume": [100000],
        })
        result = validator.validate(df, "stock_daily")
        assert not result.is_valid
        assert any("numeric" in e.message for e in result.errors)

    def test_negative_volume_flagged(self, validator: DataValidator):
        df = pd.DataFrame({
            "code": ["000001.SZ"],
            "trade_date": ["2024-01-02"],
            "open": [10.0],
            "high": [11.0],
            "low": [9.5],
            "close": [10.5],
            "volume": [-100],
        })
        result = validator.validate(df, "stock_daily")
        assert not result.is_valid
        assert any("non-negative" in e.message for e in result.errors)

    def test_stock_list_code_pattern_valid(self, validator: DataValidator):
        df = pd.DataFrame({
            "code": ["000001.SZ", "600000.SH", "430047.BJ"],
            "name": ["平安银行", "浦发银行", "诺思兰德"],
        })
        result = validator.validate(df, "stock_list")
        assert result.is_valid

    def test_stock_list_code_pattern_invalid(self, validator: DataValidator):
        df = pd.DataFrame({
            "code": ["000001", "AAPL.US"],
            "name": ["平安银行", "苹果"],
        })
        result = validator.validate(df, "stock_list")
        assert not result.is_valid
        assert any(e.column == "code" for e in result.errors)

    def test_unknown_data_type_passes(self, validator: DataValidator):
        df = pd.DataFrame({"col_a": [1, 2], "col_b": [3, 4]})
        result = validator.validate(df, "unknown_type")
        assert result.is_valid


# ====================================================================
# Business rules
# ====================================================================

class TestBusinessRules:

    def _make_daily(self, **overrides) -> pd.DataFrame:
        row = {
            "code": "000001.SZ", "trade_date": "2024-01-02",
            "open": 10.0, "high": 11.0, "low": 9.5, "close": 10.5, "volume": 100000,
        }
        row.update(overrides)
        return pd.DataFrame([row])

    def test_valid_ohlcv(self, validator: DataValidator):
        result = validator.validate(self._make_daily(), "stock_daily")
        biz_errors = [e for e in result.errors if e.level == "business"]
        assert len(biz_errors) == 0

    def test_open_zero(self, validator: DataValidator):
        result = validator.validate(self._make_daily(open=0), "stock_daily")
        assert not result.is_valid
        assert any("open" in e.column for e in result.errors)

    def test_close_negative(self, validator: DataValidator):
        result = validator.validate(self._make_daily(close=-1), "stock_daily")
        assert not result.is_valid

    def test_high_less_than_low(self, validator: DataValidator):
        result = validator.validate(self._make_daily(high=8.0, low=9.5), "stock_daily")
        assert not result.is_valid
        assert any("high" in e.message and "low" in e.message for e in result.errors)

    def test_high_less_than_open(self, validator: DataValidator):
        result = validator.validate(self._make_daily(high=9.0, open=10.0, low=8.0, close=8.5), "stock_daily")
        assert not result.is_valid

    def test_high_less_than_close(self, validator: DataValidator):
        result = validator.validate(self._make_daily(high=9.0, open=8.5, low=8.0, close=10.0), "stock_daily")
        assert not result.is_valid

    def test_low_greater_than_open(self, validator: DataValidator):
        result = validator.validate(self._make_daily(low=11.0, open=10.0, high=12.0, close=11.5), "stock_daily")
        assert not result.is_valid

    def test_low_greater_than_close(self, validator: DataValidator):
        result = validator.validate(self._make_daily(low=11.0, open=11.5, high=12.0, close=10.0), "stock_daily")
        assert not result.is_valid

    def test_negative_volume(self, validator: DataValidator):
        result = validator.validate(self._make_daily(volume=-1), "stock_daily")
        assert not result.is_valid

    def test_rows_invalid_count(self, validator: DataValidator):
        df = pd.DataFrame({
            "code": ["A", "B"],
            "trade_date": ["2024-01-02", "2024-01-03"],
            "open": [0, 10.0],
            "high": [5, 11.0],
            "low": [4, 9.5],
            "close": [4.5, 10.5],
            "volume": [100, 200],
        })
        result = validator.validate(df, "stock_daily")
        assert result.rows_invalid == 1


# ====================================================================
# Statistical checks
# ====================================================================

class TestStatistical:

    def test_pct_change_warning(self, validator: DataValidator):
        df = pd.DataFrame({
            "code": ["000001.SZ"] * 3,
            "trade_date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "open": [10.0, 10.0, 10.0],
            "high": [11.0, 11.0, 11.0],
            "low": [9.5, 9.5, 9.5],
            "close": [10.5, 10.5, 10.5],
            "volume": [100000, 100000, 100000],
            "pct_change": [5.0, -25.0, 1.0],
        })
        result = validator.validate(df, "stock_daily")
        assert len(result.warnings) >= 1
        assert any(w.column == "pct_change" for w in result.warnings)

    def test_zscore_outlier_warning(self, validator: DataValidator):
        closes = [10.0] * 200 + [10000.0]
        n = len(closes)
        df = pd.DataFrame({
            "code": ["000001.SZ"] * n,
            "trade_date": [f"2024-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}" for i in range(n)],
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "volume": [100000] * n,
        })
        result = validator.validate(df, "stock_daily")
        assert any(w.column == "close" and "Z-score" in w.message for w in result.warnings)

    def test_no_warnings_for_normal_data(self, validator: DataValidator):
        df = pd.DataFrame({
            "code": ["000001.SZ"] * 5,
            "trade_date": [f"2024-01-0{i}" for i in range(1, 6)],
            "open": [10.0, 10.1, 10.2, 10.3, 10.4],
            "high": [10.5, 10.6, 10.7, 10.8, 10.9],
            "low": [9.5, 9.6, 9.7, 9.8, 9.9],
            "close": [10.2, 10.3, 10.4, 10.5, 10.6],
            "volume": [100000] * 5,
        })
        result = validator.validate(df, "stock_daily")
        assert result.is_valid
        assert len(result.warnings) == 0

    def test_statistical_skipped_for_non_daily(self, validator: DataValidator):
        df = pd.DataFrame({
            "code": ["000001.SZ"],
            "name": ["平安银行"],
        })
        result = validator.validate(df, "stock_list")
        assert len(result.warnings) == 0

    def test_custom_limits(self):
        v = DataValidator(pct_change_limit=5.0, zscore_limit=2.0)
        df = pd.DataFrame({
            "code": ["000001.SZ"] * 3,
            "trade_date": ["2024-01-02", "2024-01-03", "2024-01-04"],
            "open": [10.0, 10.0, 10.0],
            "high": [11.0, 11.0, 11.0],
            "low": [9.5, 9.5, 9.5],
            "close": [10.5, 10.5, 10.5],
            "volume": [100000, 100000, 100000],
            "pct_change": [6.0, 1.0, -1.0],
        })
        result = v.validate(df, "stock_daily")
        assert any(w.column == "pct_change" for w in result.warnings)
