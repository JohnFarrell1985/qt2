"""Tests for src/sentiment/price_volume.py"""
from datetime import date
from unittest.mock import patch, MagicMock

import pandas as pd

from src.sentiment.price_volume import PriceVolumeCalculator


class TestCalcAdRatio:
    def test_more_up_than_down(self):
        df = pd.DataFrame({
            "change_pct": [3.0, 2.0, -1.0, 0.0, 5.0],
        })
        result = PriceVolumeCalculator._calc_ad_ratio(df)
        assert "ad_ratio" in result
        assert result["ad_ratio"] == round(3 / 1, 4)

    def test_all_down(self):
        df = pd.DataFrame({"change_pct": [-2.0, -1.5, -0.5]})
        result = PriceVolumeCalculator._calc_ad_ratio(df)
        assert result["ad_ratio"] == 0.0

    def test_no_decline(self):
        df = pd.DataFrame({"change_pct": [1.0, 2.0, 3.0]})
        result = PriceVolumeCalculator._calc_ad_ratio(df)
        assert result["ad_ratio"] == 3.0

    def test_all_flat(self):
        df = pd.DataFrame({"change_pct": [0.0, 0.0, 0.0]})
        result = PriceVolumeCalculator._calc_ad_ratio(df)
        assert result["ad_ratio"] == 0.0


class TestCalcLimitCounts:
    def test_mixed(self):
        df = pd.DataFrame({
            "change_pct": [10.0, 9.9, 9.8, -10.0, -9.8, 5.0, 0.0],
        })
        result = PriceVolumeCalculator._calc_limit_counts(df)
        assert result["limit_up_count"] == 3
        assert result["limit_down_count"] == 2

    def test_no_limits(self):
        df = pd.DataFrame({"change_pct": [1.0, -1.0, 0.5, -0.3]})
        result = PriceVolumeCalculator._calc_limit_counts(df)
        assert result["limit_up_count"] == 0
        assert result["limit_down_count"] == 0

    def test_all_limit_up(self):
        df = pd.DataFrame({"change_pct": [10.0, 9.8, 10.05]})
        result = PriceVolumeCalculator._calc_limit_counts(df)
        assert result["limit_up_count"] == 3
        assert result["limit_down_count"] == 0


class TestCalcBurstRate:
    def test_all_sealed(self):
        df = pd.DataFrame({
            "pre_close": [10.0, 20.0],
            "high": [11.0, 22.0],
            "change_pct": [10.0, 10.0],
        })
        result = PriceVolumeCalculator._calc_burst_rate(df)
        assert result["burst_rate"] == 0.0

    def test_all_burst(self):
        df = pd.DataFrame({
            "pre_close": [10.0, 20.0],
            "high": [11.0, 22.0],
            "change_pct": [5.0, 3.0],
        })
        result = PriceVolumeCalculator._calc_burst_rate(df)
        assert result["burst_rate"] == 1.0

    def test_partial_burst(self):
        df = pd.DataFrame({
            "pre_close": [10.0, 10.0, 10.0],
            "high": [11.0, 11.0, 11.0],
            "change_pct": [10.0, 5.0, 10.0],
        })
        result = PriceVolumeCalculator._calc_burst_rate(df)
        expected = round(1.0 - 2 / 3, 4)
        assert result["burst_rate"] == expected

    def test_no_touch_limit(self):
        df = pd.DataFrame({
            "pre_close": [10.0, 10.0],
            "high": [10.5, 10.3],
            "change_pct": [3.0, 2.0],
        })
        result = PriceVolumeCalculator._calc_burst_rate(df)
        assert result["burst_rate"] == 0.0


class TestCalculate:
    @patch("src.sentiment.price_volume.get_session")
    def test_returns_empty_when_no_data(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.return_value = []
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        calc = PriceVolumeCalculator()
        result = calc.calculate(date(2025, 1, 6))
        assert result == {}

    @patch("src.sentiment.price_volume.get_session")
    def test_returns_keys_with_data(self, mock_get_session):
        daily_rows = [
            ("000001", 10.0, 10.5, 9.8, 10.2, 10.0, 1000000, 10200000, 2.0),
            ("000002", 20.0, 21.0, 19.5, 20.5, 20.0, 500000, 10250000, 2.5),
            ("000003", 5.0, 5.5, 4.8, 4.9, 5.0, 800000, 3920000, -2.0),
        ]
        history_rows = [
            ("000001", date(2025, 1, 6), 10.2, 1000000, 10200000, 2.0),
            ("000002", date(2025, 1, 6), 20.5, 500000, 10250000, 2.5),
            ("000003", date(2025, 1, 6), 4.9, 800000, 3920000, -2.0),
        ]

        mock_session = MagicMock()
        mock_session.execute.return_value.fetchall.side_effect = [
            daily_rows, history_rows,
        ]
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_session)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_ctx

        calc = PriceVolumeCalculator()
        result = calc.calculate(date(2025, 1, 6))

        assert "ad_ratio" in result
        assert "limit_up_count" in result
        assert "limit_down_count" in result
        assert "burst_rate" in result
