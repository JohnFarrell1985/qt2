"""Tests for composite sentiment index (P1-16)"""
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from src.sentiment.composite_index import CompositeIndex, _zscore


class TestZscore:
    def test_normal_value(self):
        assert abs(_zscore(1.5, 1.0, 0.5) - 1.0 / 3.0) < 1e-6

    def test_zero_std(self):
        assert _zscore(5.0, 3.0, 0.0) == 0.0

    def test_clipping(self):
        result = _zscore(100.0, 0.0, 1.0)
        assert result == 1.0

    def test_negative_clipping(self):
        result = _zscore(-100.0, 0.0, 1.0)
        assert result == -1.0


class TestCompositeIndex:
    @pytest.fixture()
    def csi(self):
        return CompositeIndex()

    def test_init_loads_weights(self, csi):
        assert "earning_effect" in csi.weights
        assert "capital_mood" in csi.weights

    def test_safe_zscore_with_short_series(self, csi):
        series = pd.Series([1.0, 2.0])
        result = csi._safe_zscore(1.5, series)
        assert result == 0.0

    def test_safe_zscore_with_none(self, csi):
        series = pd.Series([1.0] * 10)
        assert csi._safe_zscore(None, series) == 0.0

    def test_safe_zscore_normal(self, csi):
        series = pd.Series(np.random.normal(1.0, 0.5, 30))
        result = csi._safe_zscore(1.0, series)
        assert -1.0 <= result <= 1.0

    def test_calc_earning_effect_empty(self, csi):
        result = csi._calc_earning_effect({}, pd.DataFrame())
        assert result == 0.0

    def test_calc_earning_effect_with_data(self, csi):
        raw = {"ad_ratio": 1.5, "limit_up_count": 30, "new_high_60d": 50}
        hist = pd.DataFrame({
            "ad_ratio": np.random.normal(1.0, 0.3, 30),
            "limit_up_count": np.random.normal(15, 5, 30),
            "new_high_60d": np.random.normal(25, 10, 30),
        })
        result = csi._calc_earning_effect(raw, hist)
        assert -1.0 <= result <= 1.0

    def test_calc_news_mood_none(self):
        assert CompositeIndex._calc_news_mood({}) == 0.0

    def test_calc_news_mood_normal(self):
        assert CompositeIndex._calc_news_mood({"news_sentiment_score": 0.5}) == 0.5

    def test_calc_news_mood_clipped(self):
        assert CompositeIndex._calc_news_mood({"news_sentiment_score": 2.0}) == 1.0

    @patch.object(CompositeIndex, "_load_sentiment_row")
    @patch.object(CompositeIndex, "_load_history")
    def test_compute_no_data(self, mock_hist, mock_row, csi):
        mock_row.return_value = None
        from datetime import date
        result = csi.compute(date(2026, 1, 1))
        assert result == {}

    @patch.object(CompositeIndex, "_load_sentiment_row")
    @patch.object(CompositeIndex, "_load_history")
    def test_compute_with_data(self, mock_hist, mock_row, csi):
        from datetime import date
        mock_row.return_value = {
            "ad_ratio": 1.2, "limit_up_count": 20, "limit_down_count": 5,
            "burst_rate": 0.3, "new_high_60d": 40, "new_low_60d": 10,
            "market_volatility_5d": 1.5, "market_volatility_20d": 1.8,
            "volume_ratio": 1.1, "sector_concentration": 0.5,
            "north_net_flow": 30.0, "margin_balance_change": 5.0,
            "news_sentiment_score": 0.2,
            "fx_usdcny": 7.2, "gold_price_usd": 2000.0, "crude_oil_usd": 80.0,
        }
        hist_data = {
            "ad_ratio": np.random.normal(1.0, 0.3, 30),
            "limit_up_count": np.random.normal(15, 5, 30),
            "limit_down_count": np.random.normal(8, 3, 30),
            "new_high_60d": np.random.normal(25, 10, 30),
            "new_low_60d": np.random.normal(15, 5, 30),
            "market_volatility_5d": np.random.normal(1.5, 0.3, 30),
            "market_volatility_20d": np.random.normal(1.8, 0.3, 30),
            "volume_ratio": np.random.normal(1.0, 0.2, 30),
            "sector_concentration": np.random.normal(0.4, 0.1, 30),
            "north_net_flow": np.random.normal(20, 15, 30),
            "margin_balance_change": np.random.normal(3, 2, 30),
            "news_sentiment_score": np.random.normal(0.1, 0.3, 30),
            "fx_usdcny": np.random.normal(7.2, 0.1, 30),
            "gold_price_usd": np.random.normal(2000, 50, 30),
            "crude_oil_usd": np.random.normal(80, 5, 30),
        }
        mock_hist.return_value = pd.DataFrame(hist_data)

        result = csi.compute(date(2026, 1, 1))
        assert "composite_sentiment" in result
        assert -1.0 <= result["composite_sentiment"] <= 1.0
        assert "earning_effect" in result
        assert "capital_mood" in result
