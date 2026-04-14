"""E2E: 因子衰减监控 — 用真实行情数据构造因子, 验证 IC/ICIR/PSI 计算"""
import numpy as np
import pandas as pd
import pytest

from src.monitoring.factor_monitor import (
    rolling_ic, calc_icir, calc_psi,
    FactorDecayMonitor, CrowdingDetector,
)


class TestRollingICWithRealData:
    """用真实多股日线构造动量因子, 计算截面 IC"""

    @pytest.fixture
    def factor_and_returns(self, real_multi_stock_daily):
        df = real_multi_stock_daily.sort_values(["trade_date", "code"]).copy()
        df["mom_20"] = df.groupby("code")["close"].transform(
            lambda x: x.pct_change(20)
        )
        df["fwd_ret_5"] = df.groupby("code")["close"].transform(
            lambda x: x.shift(-5) / x - 1
        )
        df = df.dropna(subset=["mom_20", "fwd_ret_5"]).reset_index(drop=True)
        return df

    def test_rolling_ic_produces_series(self, factor_and_returns):
        df = factor_and_returns
        ic = rolling_ic(
            df["mom_20"], df["fwd_ret_5"], df["trade_date"], window=20,
        )
        assert isinstance(ic, pd.Series)
        assert len(ic) > 0

    def test_ic_values_bounded(self, factor_and_returns):
        df = factor_and_returns
        ic = rolling_ic(
            df["mom_20"], df["fwd_ret_5"], df["trade_date"], window=20,
        )
        valid = ic.dropna()
        assert (valid.abs() <= 1.0).all(), "IC should be in [-1, 1]"

    def test_icir_from_real_ic(self, factor_and_returns):
        df = factor_and_returns
        ic = rolling_ic(
            df["mom_20"], df["fwd_ret_5"], df["trade_date"], window=20,
        )
        icir = calc_icir(ic)
        assert isinstance(icir, float)
        assert not np.isnan(icir)


class TestPSIWithRealData:
    """用真实收益率分布计算 PSI"""

    def test_psi_same_distribution(self, real_stock_daily_df):
        returns = real_stock_daily_df["change_pct"].dropna().values
        mid = len(returns) // 2
        psi = calc_psi(returns[:mid], returns[:mid])
        assert psi < 0.01, f"Same distribution PSI should be ~0, got {psi:.4f}"

    def test_psi_different_periods(self, real_stock_daily_df):
        returns = real_stock_daily_df["change_pct"].dropna().values
        mid = len(returns) // 2
        psi = calc_psi(returns[:mid], returns[mid:])
        assert psi >= 0.0
        assert not np.isnan(psi)

    def test_psi_nonnegative(self, real_stock_daily_df):
        returns = real_stock_daily_df["change_pct"].dropna().values
        mid = len(returns) // 2
        psi = calc_psi(returns[:mid], returns[mid:])
        assert psi >= 0.0


class TestFactorDecayMonitorE2E:
    """FactorDecayMonitor 端到端"""

    @pytest.fixture
    def factor_data(self, real_multi_stock_daily):
        df = real_multi_stock_daily.sort_values(["trade_date", "code"]).copy()
        df["mom_20"] = df.groupby("code")["close"].transform(
            lambda x: x.pct_change(20)
        )
        df["fwd_ret_5"] = df.groupby("code")["close"].transform(
            lambda x: x.shift(-5) / x - 1
        )
        df = df.dropna(subset=["mom_20", "fwd_ret_5"]).reset_index(drop=True)
        return df

    def test_check_decay_returns_complete_report(self, factor_data):
        monitor = FactorDecayMonitor(ic_warning=0.02, icir_warning=0.3)
        result = monitor.check_decay(
            factor_data["mom_20"],
            factor_data["fwd_ret_5"],
            factor_data["trade_date"],
        )
        assert "ic_mean" in result
        assert "icir" in result
        assert "psi" in result
        assert "level" in result
        assert "action" in result
        assert result["level"] in ("normal", "warning", "critical")
        assert result["action"] in ("continue", "review_factor", "retrain_model")

    def test_check_decay_with_reference(self, factor_data):
        mid = len(factor_data) // 2
        ref_vals = factor_data["mom_20"].iloc[:mid].values
        monitor = FactorDecayMonitor()
        result = monitor.check_decay(
            factor_data["mom_20"],
            factor_data["fwd_ret_5"],
            factor_data["trade_date"],
            reference_values=ref_vals,
        )
        assert result["psi"] >= 0.0


class TestCrowdingDetectorE2E:
    """CrowdingDetector 用真实数据"""

    def test_hhi_with_equal_weights(self):
        detector = CrowdingDetector()
        weights = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
        hhi = detector.herfindahl_index(weights)
        assert abs(hhi - 0.2) < 0.001

    def test_hhi_concentrated(self):
        detector = CrowdingDetector()
        weights = np.array([0.95, 0.01, 0.01, 0.01, 0.02])
        hhi = detector.herfindahl_index(weights)
        assert hhi > 0.8

    def test_volume_anomaly_with_real_data(self, real_stock_daily_df):
        detector = CrowdingDetector()
        vol = real_stock_daily_df["volume"].astype(float)
        hist_mean = vol.iloc[:-20].mean()
        recent_mean = vol.iloc[-5:].mean()
        ratio = detector.volume_anomaly(recent_mean, hist_mean)
        assert ratio > 0

    def test_cross_factor_correlation(self, real_multi_stock_daily):
        df = real_multi_stock_daily.sort_values(["trade_date", "code"]).copy()
        df["mom_5"] = df.groupby("code")["close"].transform(lambda x: x.pct_change(5))
        df["mom_20"] = df.groupby("code")["close"].transform(lambda x: x.pct_change(20))

        detector = CrowdingDetector()
        single_code = df[df["code"] == "000001"].dropna(subset=["mom_5", "mom_20"])
        corr = detector.cross_factor_correlation(
            single_code["mom_5"], single_code["mom_20"],
        )
        assert -1.0 <= corr <= 1.0

    def test_detect_comprehensive(self, real_stock_daily_df):
        detector = CrowdingDetector()
        vol = real_stock_daily_df["volume"].astype(float)

        result = detector.detect(
            weights=np.array([0.3, 0.3, 0.2, 0.1, 0.1]),
            recent_vol=vol.iloc[-5:].mean(),
            hist_vol=vol.iloc[:-20].mean(),
        )
        assert "hhi" in result
        assert "volume_ratio" in result
        assert "crowding_score" in result
        assert "action" in result
        assert 0 <= result["crowding_score"] <= 1
