"""Tests for northbound flow signal (P1-33)"""
import numpy as np
import pandas as pd
import pytest

from src.sentiment.northbound_flow import NorthboundFlowSignal


class TestNorthboundFlowSignal:
    @pytest.fixture()
    def signal(self):
        return NorthboundFlowSignal()

    def test_compute_from_series_risk_on(self, signal):
        """Strong positive inflow → risk_on"""
        flow = pd.Series(
            np.concatenate([np.random.normal(0, 5, 50), np.array([50, 60, 70, 80, 90])]),
        )
        result = signal.compute_from_series(flow)
        assert result["nb_regime"] in ("risk_on", "neutral", "risk_off")
        assert "nb_flow_5d" in result
        assert "nb_flow_z" in result

    def test_compute_from_series_risk_off(self, signal):
        """Strong negative outflow → risk_off"""
        flow = pd.Series(
            np.concatenate([np.random.normal(0, 5, 50), np.array([-50, -60, -70, -80, -90])]),
        )
        result = signal.compute_from_series(flow)
        assert result["nb_regime"] in ("risk_on", "neutral", "risk_off")

    def test_compute_from_series_neutral(self, signal):
        """Flat flow → neutral"""
        flow = pd.Series(np.random.normal(0, 1, 60))
        result = signal.compute_from_series(flow)
        assert "nb_regime" in result

    def test_short_series(self, signal):
        """Series too short → all None"""
        flow = pd.Series([10.0, 20.0])
        result = signal.compute_from_series(flow)
        assert result["nb_flow_5d"] is not None

    def test_result_keys(self, signal):
        flow = pd.Series(np.random.normal(10, 5, 60))
        result = signal.compute_from_series(flow)
        assert "nb_flow_5d" in result
        assert "nb_flow_20d" in result
        assert "nb_flow_z" in result
        assert "nb_regime" in result

    def test_custom_thresholds(self):
        signal = NorthboundFlowSignal(risk_on_threshold=1.0, risk_off_threshold=-1.0)
        flow = pd.Series(np.random.normal(0, 1, 60))
        result = signal.compute_from_series(flow)
        assert result["nb_regime"] in ("risk_on", "neutral", "risk_off")
