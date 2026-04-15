"""Tests for P2-03/P2-05 enhanced performance functions in src/backtest/performance.py.

Covers: rolling_sharpe, bootstrap_sharpe_pvalue, information_ratio,
        monthly_returns_heatmap, turnover_analysis.
"""
import numpy as np
import pandas as pd
import pytest

from src.backtest.performance import (
    rolling_sharpe,
    bootstrap_sharpe_pvalue,
    information_ratio,
    monthly_returns_heatmap,
    turnover_analysis,
)


@pytest.fixture
def equity_curve_252():
    """252 trading-day equity curve with mild positive drift."""
    dates = pd.date_range("2025-01-01", periods=252, freq="B")
    np.random.seed(42)
    capitals = [1_000_000.0]
    for _ in range(251):
        capitals.append(capitals[-1] * (1 + np.random.normal(0.0004, 0.012)))
    return [{"date": str(d.date()), "capital": c} for d, c in zip(dates, capitals)]


@pytest.fixture
def benchmark_curve_252():
    """252 trading-day benchmark curve (slower drift)."""
    dates = pd.date_range("2025-01-01", periods=252, freq="B")
    np.random.seed(99)
    capitals = [1_000_000.0]
    for _ in range(251):
        capitals.append(capitals[-1] * (1 + np.random.normal(0.0002, 0.010)))
    return [{"date": str(d.date()), "capital": c} for d, c in zip(dates, capitals)]


@pytest.fixture
def short_equity():
    """Too short for meaningful statistics."""
    dates = pd.date_range("2025-01-01", periods=10, freq="B")
    capitals = [1_000_000 + i * 1000 for i in range(10)]
    return [{"date": str(d.date()), "capital": c} for d, c in zip(dates, capitals)]


@pytest.fixture
def sample_trades():
    return [
        {"amount": 50000, "fees": 25, "slippage": 5, "strategy_name": "momentum", "direction": "buy"},
        {"amount": 30000, "fees": 15, "slippage": 3, "strategy_name": "momentum", "direction": "sell"},
        {"amount": 20000, "fees": 10, "slippage": 2, "strategy_name": "mean_reversion", "direction": "buy"},
    ]


# ── rolling_sharpe ──────────────────────────────────────────────────


class TestRollingSharpe:
    @pytest.mark.timeout(30)
    def test_returns_series(self, equity_curve_252):
        rs = rolling_sharpe(equity_curve_252, window=60)
        assert isinstance(rs, pd.Series)
        assert len(rs) > 0

    @pytest.mark.timeout(30)
    def test_length_matches_window(self, equity_curve_252):
        rs = rolling_sharpe(equity_curve_252, window=60)
        assert len(rs) <= 252 - 60 + 1

    @pytest.mark.timeout(30)
    def test_values_are_finite(self, equity_curve_252):
        rs = rolling_sharpe(equity_curve_252, window=60)
        assert rs.notna().all()

    @pytest.mark.timeout(30)
    def test_short_curve_returns_empty(self, short_equity):
        rs = rolling_sharpe(short_equity, window=60)
        assert len(rs) == 0

    @pytest.mark.timeout(30)
    def test_custom_window(self, equity_curve_252):
        rs20 = rolling_sharpe(equity_curve_252, window=20)
        rs120 = rolling_sharpe(equity_curve_252, window=120)
        assert len(rs20) > len(rs120)


# ── bootstrap_sharpe_pvalue ─────────────────────────────────────────


class TestBootstrapSharpePvalue:
    @pytest.mark.timeout(30)
    def test_returns_float(self, equity_curve_252):
        pv = bootstrap_sharpe_pvalue(equity_curve_252, n_bootstrap=200)
        assert isinstance(pv, float)
        assert 0.0 <= pv <= 1.0

    @pytest.mark.timeout(30)
    def test_short_curve_returns_one(self, short_equity):
        pv = bootstrap_sharpe_pvalue(short_equity)
        assert pv == 1.0

    @pytest.mark.timeout(30)
    def test_positive_drift_low_pvalue(self):
        dates = pd.date_range("2025-01-01", periods=252, freq="B")
        np.random.seed(7)
        capitals = [1_000_000.0]
        for _ in range(251):
            capitals.append(capitals[-1] * (1 + np.random.normal(0.002, 0.008)))
        ec = [{"date": str(d.date()), "capital": c} for d, c in zip(dates, capitals)]
        pv = bootstrap_sharpe_pvalue(ec, n_bootstrap=500)
        assert pv < 0.3

    @pytest.mark.timeout(30)
    def test_reproducible_with_seed(self, equity_curve_252):
        pv1 = bootstrap_sharpe_pvalue(equity_curve_252, n_bootstrap=200)
        pv2 = bootstrap_sharpe_pvalue(equity_curve_252, n_bootstrap=200)
        assert pv1 == pv2


# ── information_ratio ───────────────────────────────────────────────


class TestInformationRatio:
    @pytest.mark.timeout(30)
    def test_returns_dict_with_keys(self, equity_curve_252, benchmark_curve_252):
        ir = information_ratio(equity_curve_252, benchmark_curve_252)
        assert isinstance(ir, dict)
        assert "ir" in ir
        assert "tracking_error" in ir
        assert "annualized_excess_return" in ir

    @pytest.mark.timeout(30)
    def test_values_are_finite(self, equity_curve_252, benchmark_curve_252):
        ir = information_ratio(equity_curve_252, benchmark_curve_252)
        for v in ir.values():
            assert np.isfinite(v)

    @pytest.mark.timeout(30)
    def test_short_curves_return_zeros(self, short_equity):
        ir = information_ratio(short_equity, short_equity)
        assert ir["ir"] == 0.0
        assert ir["tracking_error"] == 0.0

    @pytest.mark.timeout(30)
    def test_same_curve_zero_ir(self, equity_curve_252):
        ir = information_ratio(equity_curve_252, equity_curve_252)
        assert ir["tracking_error"] == 0.0


# ── monthly_returns_heatmap ─────────────────────────────────────────


class TestMonthlyReturnsHeatmap:
    @pytest.mark.timeout(30)
    def test_returns_nested_dict(self, equity_curve_252):
        hm = monthly_returns_heatmap(equity_curve_252)
        assert isinstance(hm, dict)
        assert len(hm) > 0

    @pytest.mark.timeout(30)
    def test_year_month_structure(self, equity_curve_252):
        hm = monthly_returns_heatmap(equity_curve_252)
        for year, months in hm.items():
            assert year.isdigit()
            assert isinstance(months, dict)
            for m, v in months.items():
                assert m.isdigit()
                assert isinstance(v, float)

    @pytest.mark.timeout(30)
    def test_empty_curve_returns_empty(self):
        assert monthly_returns_heatmap([]) == {}

    @pytest.mark.timeout(30)
    def test_single_point_returns_at_most_one_month(self):
        ec = [{"date": "2025-01-01", "capital": 1_000_000}]
        hm = monthly_returns_heatmap(ec)
        total_months = sum(len(months) for months in hm.values())
        assert total_months <= 1


# ── turnover_analysis ───────────────────────────────────────────────


class TestTurnoverAnalysis:
    @pytest.mark.timeout(30)
    def test_returns_all_keys(self, sample_trades, equity_curve_252):
        result = turnover_analysis(sample_trades, equity_curve_252)
        expected_keys = {
            "annualized_turnover_pct", "total_fees", "total_slippage",
            "gross_return_pct", "fee_to_gross_pct", "net_sharpe",
            "per_strategy_turnover",
        }
        assert expected_keys <= set(result.keys())

    @pytest.mark.timeout(30)
    def test_values_are_finite(self, sample_trades, equity_curve_252):
        result = turnover_analysis(sample_trades, equity_curve_252)
        for k, v in result.items():
            if isinstance(v, (int, float)):
                assert np.isfinite(v), f"{k} is not finite"

    @pytest.mark.timeout(30)
    def test_total_fees(self, sample_trades, equity_curve_252):
        result = turnover_analysis(sample_trades, equity_curve_252)
        assert result["total_fees"] == 50.0
        assert result["total_slippage"] == 10.0

    @pytest.mark.timeout(30)
    def test_per_strategy_turnover(self, sample_trades, equity_curve_252):
        result = turnover_analysis(sample_trades, equity_curve_252)
        pst = result["per_strategy_turnover"]
        assert "momentum" in pst
        assert "mean_reversion" in pst

    @pytest.mark.timeout(30)
    def test_empty_trades_returns_zeros(self, equity_curve_252):
        result = turnover_analysis([], equity_curve_252)
        assert result["annualized_turnover_pct"] == 0.0
        assert result["total_fees"] == 0.0

    @pytest.mark.timeout(30)
    def test_empty_equity_returns_zeros(self, sample_trades):
        result = turnover_analysis(sample_trades, [])
        assert result["annualized_turnover_pct"] == 0.0

    @pytest.mark.timeout(30)
    def test_single_day_equity(self, sample_trades):
        ec = [{"date": "2025-01-01", "capital": 1_000_000}]
        result = turnover_analysis(sample_trades, ec)
        assert result["annualized_turnover_pct"] == 0.0
