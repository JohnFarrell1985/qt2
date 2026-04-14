"""Tests for factor quality gate (P1-34)"""
import numpy as np
import pandas as pd
import pytest

from src.factor.quality_gate import FactorQualityGate


class TestFactorQualityGate:
    @pytest.fixture()
    def gate(self):
        return FactorQualityGate()

    @pytest.fixture()
    def synthetic_data(self):
        """Generate synthetic factor + return data for testing"""
        np.random.seed(42)
        n_dates = 60
        n_stocks = 50

        dates = pd.date_range("2024-01-01", periods=n_dates, freq="B")
        stocks = [f"{i:06d}.SZ" for i in range(n_stocks)]

        rows = []
        for dt in dates:
            for code in stocks:
                rows.append((dt, code))
        idx = pd.MultiIndex.from_tuples(rows, names=["trade_date", "code"])

        good_factor = np.random.normal(0, 1, len(idx))
        bad_factor = np.random.normal(0, 1, len(idx))
        forward_return = good_factor * 0.05 + np.random.normal(0, 0.02, len(idx))

        factor_df = pd.DataFrame(
            {"good_factor": good_factor, "bad_factor": bad_factor},
            index=idx,
        )
        return_df = pd.DataFrame(
            {"forward_return": forward_return},
            index=idx,
        )
        return factor_df, return_df

    def test_evaluate_good_factor(self, gate, synthetic_data):
        factor_df, return_df = synthetic_data
        result = gate.evaluate(factor_df, return_df, "good_factor")
        assert "ic_mean" in result
        assert "icir" in result
        assert "quantile_spread" in result
        assert "monotonicity" in result
        assert result["factor_name"] == "good_factor"
        assert result["ic_mean"] is not None

    def test_evaluate_bad_factor(self, gate, synthetic_data):
        factor_df, return_df = synthetic_data
        result = gate.evaluate(factor_df, return_df, "bad_factor")
        assert result["factor_name"] == "bad_factor"

    def test_batch_evaluate(self, gate, synthetic_data):
        factor_df, return_df = synthetic_data
        results = gate.batch_evaluate(factor_df, return_df)
        assert len(results) == 2
        assert all("passed" in r for r in results)

    def test_monotonicity_score_increasing(self):
        score = FactorQualityGate._monotonicity_score([1, 2, 3, 4, 5])
        assert score == 1.0

    def test_monotonicity_score_decreasing(self):
        score = FactorQualityGate._monotonicity_score([5, 4, 3, 2, 1])
        assert score == 1.0

    def test_monotonicity_score_random(self):
        score = FactorQualityGate._monotonicity_score([3, 1, 4, 2, 5])
        assert 0.0 <= score <= 1.0

    def test_monotonicity_score_short(self):
        score = FactorQualityGate._monotonicity_score([1])
        assert score == 0.0

    def test_custom_criteria(self, synthetic_data):
        """Strict criteria should reject even moderately good factors"""
        factor_df, return_df = synthetic_data
        strict_gate = FactorQualityGate(criteria={
            "ic_mean_abs": 0.5, "icir_abs": 2.0,
            "quantile_spread": 0.1, "monotonicity": 0.99,
        })
        result = strict_gate.evaluate(factor_df, return_df, "bad_factor")
        assert result["passed"] is False

    def test_short_ic_series(self, gate):
        """Factor with too few dates → not passed"""
        idx = pd.MultiIndex.from_tuples(
            [(pd.Timestamp("2024-01-01"), "000001.SZ")],
            names=["trade_date", "code"],
        )
        factor_df = pd.DataFrame({"f1": [1.0]}, index=idx)
        return_df = pd.DataFrame({"forward_return": [0.01]}, index=idx)
        result = gate.evaluate(factor_df, return_df, "f1")
        assert result["passed"] is False
