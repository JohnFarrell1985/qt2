"""Tests for src/ml/model_evaluation.py - evaluate_predictions"""
import numpy as np
import pandas as pd
import pytest

from src.ml.model_evaluation import evaluate_predictions


def _make_multiindex_series(n_dates=10, n_stocks=50, seed=42, name="value"):
    """Create a MultiIndex(trade_date, code) Series with random data."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2024-01-01", periods=n_dates)
    codes = [f"{i:06d}" for i in range(1, n_stocks + 1)]
    index = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])
    return pd.Series(rng.randn(len(index)) * 0.01, index=index, name=name)


@pytest.fixture
def predictions_and_actuals():
    preds = _make_multiindex_series(n_dates=10, n_stocks=50, seed=42, name="predicted")
    actuals = _make_multiindex_series(n_dates=10, n_stocks=50, seed=99, name="actual")
    return preds, actuals


class TestEvaluatePredictions:
    def test_return_keys(self, predictions_and_actuals):
        preds, actuals = predictions_and_actuals
        result = evaluate_predictions(preds, actuals, n_groups=5)

        expected_keys = {
            "overall_ic", "ic_mean", "ic_std", "icir",
            "group_returns", "long_short_return", "n_samples", "n_periods",
        }
        assert set(result.keys()) == expected_keys

    def test_overall_ic_bounded(self, predictions_and_actuals):
        preds, actuals = predictions_and_actuals
        result = evaluate_predictions(preds, actuals)
        assert -1.0 <= result["overall_ic"] <= 1.0

    def test_n_samples_matches(self, predictions_and_actuals):
        preds, actuals = predictions_and_actuals
        result = evaluate_predictions(preds, actuals)
        common = preds.index.intersection(actuals.index)
        assert result["n_samples"] == len(common)

    def test_group_returns_has_labels(self, predictions_and_actuals):
        preds, actuals = predictions_and_actuals
        result = evaluate_predictions(preds, actuals, n_groups=5)
        gr = result["group_returns"]
        assert isinstance(gr, dict)
        for i in range(1, 6):
            assert f"G{i}" in gr

    def test_long_short_is_g5_minus_g1(self, predictions_and_actuals):
        preds, actuals = predictions_and_actuals
        result = evaluate_predictions(preds, actuals, n_groups=5)
        gr = result["group_returns"]
        expected = gr.get("G5", 0) - gr.get("G1", 0)
        assert abs(result["long_short_return"] - round(expected, 4)) < 1e-6

    def test_icir_is_mean_over_std(self, predictions_and_actuals):
        preds, actuals = predictions_and_actuals
        result = evaluate_predictions(preds, actuals)
        if result["ic_std"] and result["ic_std"] > 0 and result["ic_mean"] is not None:
            expected_icir = round(result["ic_mean"] / result["ic_std"], 4)
            assert abs(result["icir"] - expected_icir) < 0.01

    def test_n_groups_3(self, predictions_and_actuals):
        preds, actuals = predictions_and_actuals
        result = evaluate_predictions(preds, actuals, n_groups=3)
        assert "G1" in result["group_returns"]
        assert "G3" in result["group_returns"]

    def test_perfect_prediction_high_ic(self):
        rng = np.random.RandomState(7)
        dates = pd.bdate_range("2024-01-01", periods=5)
        codes = [f"{i:06d}" for i in range(1, 51)]
        index = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])
        actual = pd.Series(rng.randn(len(index)), index=index)
        pred = actual + rng.randn(len(index)) * 0.01
        result = evaluate_predictions(pred, actual)
        assert result["overall_ic"] > 0.9

    def test_partial_overlap(self):
        dates1 = pd.bdate_range("2024-01-01", periods=5)
        dates2 = pd.bdate_range("2024-01-03", periods=5)
        codes = [f"{i:06d}" for i in range(1, 31)]
        idx1 = pd.MultiIndex.from_product([dates1, codes], names=["trade_date", "code"])
        idx2 = pd.MultiIndex.from_product([dates2, codes], names=["trade_date", "code"])
        rng = np.random.RandomState(0)
        preds = pd.Series(rng.randn(len(idx1)), index=idx1)
        actuals = pd.Series(rng.randn(len(idx2)), index=idx2)
        result = evaluate_predictions(preds, actuals)
        assert result["n_samples"] < len(idx1)
        assert result["n_samples"] > 0

    def test_no_daily_ic_when_small_cross_section(self):
        """With fewer than 20 stocks per date, daily IC is skipped."""
        dates = pd.bdate_range("2024-01-01", periods=3)
        codes = [f"{i:06d}" for i in range(1, 6)]
        index = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])
        rng = np.random.RandomState(0)
        preds = pd.Series(rng.randn(len(index)), index=index)
        actuals = pd.Series(rng.randn(len(index)), index=index)
        result = evaluate_predictions(preds, actuals)
        assert result["n_periods"] == 0
        assert result["ic_mean"] is None
