"""Tests for factor decay monitoring."""
import numpy as np
import pandas as pd
import pytest

from src.monitoring.factor_monitor import (
    CrowdingDetector,
    FactorDecayMonitor,
    calc_icir,
    calc_psi,
    rolling_ic,
)


@pytest.fixture()
def daily_factor_data():
    """Synthetic factor data: 60 dates × 30 stocks with known correlation."""
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2024-01-01", periods=60)
    records = []
    for d in dates:
        for _ in range(30):
            factor_val = rng.standard_normal()
            ret = 0.5 * factor_val + 0.5 * rng.standard_normal()
            records.append({"date": d, "factor": factor_val, "ret": ret})
    df = pd.DataFrame(records)
    return df


class TestRollingIC:
    def test_returns_series(self, daily_factor_data):
        df = daily_factor_data
        result = rolling_ic(df["factor"], df["ret"], df["date"], window=10)
        assert isinstance(result, pd.Series)
        assert len(result) > 0

    def test_positive_ic_for_correlated_data(self, daily_factor_data):
        df = daily_factor_data
        result = rolling_ic(df["factor"], df["ret"], df["date"], window=10)
        assert result.iloc[-1] > 0, "IC should be positive for positively correlated data"

    def test_near_zero_ic_for_random_data(self):
        rng = np.random.default_rng(99)
        dates = pd.bdate_range("2024-01-01", periods=60)
        factor_vals, ret_vals, date_vals = [], [], []
        for d in dates:
            for _ in range(50):
                factor_vals.append(rng.standard_normal())
                ret_vals.append(rng.standard_normal())
                date_vals.append(d)
        result = rolling_ic(
            pd.Series(factor_vals), pd.Series(ret_vals),
            pd.Series(date_vals), window=20,
        )
        assert abs(result.iloc[-1]) < 0.15


class TestCalcICIR:
    def test_positive_icir(self):
        ic = pd.Series([0.05, 0.06, 0.04, 0.05, 0.07])
        assert calc_icir(ic) > 0

    def test_zero_std(self):
        ic = pd.Series([0.05, 0.05, 0.05])
        assert calc_icir(ic) == 0.0

    def test_high_icir_for_stable_ic(self):
        ic = pd.Series([0.05] * 10 + [0.06] * 10)
        icir = calc_icir(ic)
        assert icir > 1.0


class TestCalcPSI:
    def test_identical_distributions(self):
        rng = np.random.default_rng(42)
        data = rng.standard_normal(1000)
        psi = calc_psi(data, data)
        assert psi < 0.05

    def test_shifted_distribution(self):
        rng = np.random.default_rng(42)
        ref = rng.standard_normal(1000)
        cur = rng.standard_normal(1000) + 2.0
        psi = calc_psi(ref, cur)
        assert psi > 0.2

    def test_non_negative(self):
        rng = np.random.default_rng(42)
        a = rng.standard_normal(500)
        b = rng.standard_normal(500) + 0.5
        psi = calc_psi(a, b)
        assert psi >= 0.0


class TestFactorDecayMonitor:
    def test_normal_level(self, daily_factor_data):
        df = daily_factor_data
        monitor = FactorDecayMonitor(
            ic_warning=0.001, icir_warning=0.1,
            psi_warning=0.5, psi_critical=1.0, ic_window=10,
        )
        result = monitor.check_decay(df["factor"], df["ret"], df["date"])
        assert result["level"] == "normal"
        assert result["action"] == "continue"
        assert "ic_mean" in result
        assert "icir" in result
        assert "psi" in result

    def test_warning_level_low_ic(self):
        rng = np.random.default_rng(99)
        dates = pd.bdate_range("2024-01-01", periods=60)
        factor_vals, ret_vals, date_vals = [], [], []
        for d in dates:
            for _ in range(30):
                factor_vals.append(rng.standard_normal())
                ret_vals.append(rng.standard_normal())
                date_vals.append(d)
        monitor = FactorDecayMonitor(
            ic_warning=0.5, icir_warning=5.0,
            psi_warning=0.2, psi_critical=0.4, ic_window=10,
        )
        result = monitor.check_decay(
            pd.Series(factor_vals), pd.Series(ret_vals), pd.Series(date_vals),
        )
        assert result["level"] in ("warning", "critical")

    def test_critical_level_high_psi(self, daily_factor_data):
        df = daily_factor_data
        rng = np.random.default_rng(42)
        ref = rng.standard_normal(len(df)) + 5.0
        monitor = FactorDecayMonitor(
            ic_warning=0.001, icir_warning=0.01,
            psi_warning=0.1, psi_critical=0.2, ic_window=10,
        )
        result = monitor.check_decay(
            df["factor"], df["ret"], df["date"],
            reference_values=ref,
        )
        assert result["level"] == "critical"
        assert result["action"] == "retrain_model"


class TestCrowdingDetector:
    def test_hhi_equal_weights(self):
        detector = CrowdingDetector()
        w = np.ones(10)
        hhi = detector.herfindahl_index(w)
        assert abs(hhi - 0.1) < 1e-6

    def test_hhi_concentrated(self):
        detector = CrowdingDetector()
        w = np.array([1.0, 0.0, 0.0, 0.0])
        assert abs(detector.herfindahl_index(w) - 1.0) < 1e-6

    def test_hhi_empty(self):
        detector = CrowdingDetector()
        assert detector.herfindahl_index(np.zeros(5)) == 0.0

    def test_volume_anomaly(self):
        detector = CrowdingDetector()
        assert abs(detector.volume_anomaly(200.0, 100.0) - 2.0) < 1e-6
        assert detector.volume_anomaly(100.0, 0.0) == 0.0

    def test_detect_output_keys(self):
        detector = CrowdingDetector()
        result = detector.detect(np.ones(10), 100.0, 100.0)
        assert "hhi" in result
        assert "volume_ratio" in result
        assert "cross_corr" in result
        assert "crowding_score" in result
        assert "action" in result

    def test_detect_with_factors(self):
        detector = CrowdingDetector()
        rng = np.random.default_rng(42)
        fa = pd.Series(rng.standard_normal(100))
        fb = pd.Series(fa + rng.standard_normal(100) * 0.01)
        result = detector.detect(np.ones(5), 100.0, 100.0, fa, fb)
        assert result["cross_corr"] > 0.5
