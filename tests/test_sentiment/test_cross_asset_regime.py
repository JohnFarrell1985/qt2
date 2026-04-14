"""Tests for cross-asset regime context (P1-37)"""
import numpy as np
import pandas as pd
import pytest

from src.sentiment.cross_asset_regime import CrossAssetRegime


class TestCrossAssetRegime:
    @pytest.fixture()
    def regime(self):
        return CrossAssetRegime(momentum_window=20)

    def test_compute_from_prices_all_up(self, regime):
        """All assets trending up → risk_on"""
        prices = {
            "gold": pd.Series(np.linspace(100, 120, 30)),
            "copper": pd.Series(np.linspace(50, 60, 30)),
            "sp500": pd.Series(np.linspace(4000, 4500, 30)),
        }
        result = regime.compute_from_prices(prices)
        assert result["cross_asset_regime"] == "risk_on"
        assert result["cross_asset_risk_score"] > 0.6

    def test_compute_from_prices_all_down(self, regime):
        """All assets trending down → risk_off"""
        prices = {
            "gold": pd.Series(np.linspace(120, 100, 30)),
            "copper": pd.Series(np.linspace(60, 50, 30)),
            "sp500": pd.Series(np.linspace(4500, 4000, 30)),
        }
        result = regime.compute_from_prices(prices)
        assert result["cross_asset_regime"] == "risk_off"
        assert result["cross_asset_risk_score"] < 0.4

    def test_compute_from_prices_mixed(self, regime):
        """Mixed signals → neutral"""
        prices = {
            "gold": pd.Series(np.linspace(100, 120, 30)),
            "copper": pd.Series(np.linspace(60, 50, 30)),
        }
        result = regime.compute_from_prices(prices)
        assert result["cross_asset_regime"] == "neutral"
        assert 0.4 <= result["cross_asset_risk_score"] <= 0.6

    def test_compute_from_prices_empty(self, regime):
        result = regime.compute_from_prices({})
        assert result["cross_asset_regime"] == "neutral"
        assert result["cross_asset_risk_score"] == 0.5

    def test_compute_from_prices_short_series(self, regime):
        """Series shorter than momentum_window → skip"""
        prices = {"gold": pd.Series([100, 101, 102])}
        result = regime.compute_from_prices(prices)
        assert result["cross_asset_regime"] == "neutral"

    def test_result_structure(self, regime):
        prices = {"gold": pd.Series(np.linspace(100, 120, 30))}
        result = regime.compute_from_prices(prices)
        assert "cross_asset_risk_score" in result
        assert "cross_asset_regime" in result
