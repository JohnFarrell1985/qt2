"""Tests for src/backtest/performance.py"""
import numpy as np
import pandas as pd
import pytest

from src.backtest.performance import (
    calc_returns,
    annualized_return,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    calmar_ratio,
    win_rate,
    profit_loss_ratio,
    monthly_returns,
    full_performance_report,
)


@pytest.fixture
def equity_curve():
    """A 252-day equity curve with known growth (~26% total)."""
    dates = pd.date_range("2025-01-01", periods=252, freq="B")
    capitals = [1_000_000]
    np.random.seed(42)
    for _ in range(251):
        daily_ret = 1 + np.random.normal(0.001, 0.015)
        capitals.append(capitals[-1] * daily_ret)
    return [{"date": str(d.date()), "capital": c} for d, c in zip(dates, capitals)]


@pytest.fixture
def flat_curve():
    dates = pd.date_range("2025-01-01", periods=30, freq="B")
    return [{"date": str(d.date()), "capital": 1_000_000} for d in dates]


@pytest.fixture
def declining_curve():
    dates = pd.date_range("2025-01-01", periods=60, freq="B")
    capitals = [1_000_000 * (1 - 0.005 * i) for i in range(60)]
    return [{"date": str(d.date()), "capital": c} for d, c in zip(dates, capitals)]


@pytest.fixture
def sample_trades():
    return [
        {"profit": 500},
        {"profit": -200},
        {"profit": 300},
        {"profit": -100},
        {"profit": 800},
        {"profit": -50},
    ]


# ---- calc_returns ----

class TestCalcReturns:
    def test_returns_series(self, equity_curve):
        r = calc_returns(equity_curve)
        assert isinstance(r, pd.Series)

    def test_length(self, equity_curve):
        r = calc_returns(equity_curve)
        assert len(r) == len(equity_curve) - 1

    def test_empty_curve(self):
        r = calc_returns([])
        assert len(r) == 0

    def test_single_point(self):
        r = calc_returns([{"date": "2025-01-01", "capital": 1_000_000}])
        assert len(r) == 0

    def test_known_return(self):
        curve = [
            {"date": "2025-01-01", "capital": 100},
            {"date": "2025-01-02", "capital": 110},
        ]
        r = calc_returns(curve)
        assert pytest.approx(r.iloc[0], rel=1e-6) == 0.1


# ---- annualized_return ----

class TestAnnualizedReturn:
    def test_positive_return(self, equity_curve):
        ar = annualized_return(equity_curve)
        assert ar > 0

    def test_empty_curve(self):
        assert annualized_return([]) == 0.0

    def test_single_point(self):
        assert annualized_return([{"date": "2025-01-01", "capital": 1e6}]) == 0.0

    def test_known_value(self):
        curve = [
            {"date": "2025-01-01", "capital": 1_000_000},
            {"date": "2026-01-01", "capital": 1_100_000},
        ]
        ar = annualized_return(curve)
        assert pytest.approx(ar, rel=0.01) == 10.0

    def test_zero_start_capital(self):
        curve = [
            {"date": "2025-01-01", "capital": 0},
            {"date": "2025-07-01", "capital": 100},
        ]
        assert annualized_return(curve) == 0.0

    def test_same_day(self):
        curve = [
            {"date": "2025-01-01", "capital": 100},
            {"date": "2025-01-01", "capital": 110},
        ]
        assert annualized_return(curve) == 0.0


# ---- max_drawdown ----

class TestMaxDrawdown:
    def test_has_drawdown(self, equity_curve):
        dd = max_drawdown(equity_curve)
        assert dd["max_drawdown_pct"] > 0

    def test_empty_curve(self):
        dd = max_drawdown([])
        assert dd["max_drawdown_pct"] == 0.0
        assert dd["peak_date"] is None

    def test_single_point(self):
        dd = max_drawdown([{"date": "2025-01-01", "capital": 1e6}])
        assert dd["max_drawdown_pct"] == 0.0

    def test_monotonically_increasing(self):
        curve = [{"date": f"2025-01-{i+1:02d}", "capital": 1e6 + i * 1000} for i in range(20)]
        dd = max_drawdown(curve)
        assert dd["max_drawdown_pct"] == 0.0

    def test_known_drawdown(self):
        curve = [
            {"date": "2025-01-01", "capital": 100},
            {"date": "2025-01-02", "capital": 120},
            {"date": "2025-01-03", "capital": 90},
            {"date": "2025-01-04", "capital": 110},
        ]
        dd = max_drawdown(curve)
        expected = (120 - 90) / 120 * 100
        assert pytest.approx(dd["max_drawdown_pct"], abs=0.01) == expected
        assert dd["peak_date"] == "2025-01-02"
        assert dd["trough_date"] == "2025-01-03"

    def test_declining_curve(self, declining_curve):
        dd = max_drawdown(declining_curve)
        assert dd["max_drawdown_pct"] > 0


# ---- sharpe_ratio ----

class TestSharpeRatio:
    def test_returns_float(self, equity_curve):
        sr = sharpe_ratio(equity_curve)
        assert isinstance(sr, float)

    def test_too_few_returns(self):
        curve = [
            {"date": "2025-01-01", "capital": 100},
            {"date": "2025-01-02", "capital": 101},
        ]
        assert sharpe_ratio(curve) == 0.0

    def test_flat_curve_zero_vol(self, flat_curve):
        assert sharpe_ratio(flat_curve) == 0.0

    def test_custom_risk_free(self, equity_curve):
        sr_low = sharpe_ratio(equity_curve, risk_free_rate=0.01)
        sr_high = sharpe_ratio(equity_curve, risk_free_rate=0.10)
        assert sr_low > sr_high


# ---- sortino_ratio ----

class TestSortinoRatio:
    def test_returns_float(self, equity_curve):
        sr = sortino_ratio(equity_curve)
        assert isinstance(sr, float)

    def test_too_few_returns(self):
        curve = [{"date": "2025-01-01", "capital": 100}, {"date": "2025-01-02", "capital": 101}]
        assert sortino_ratio(curve) == 0.0

    def test_all_positive_returns_zero(self):
        """No downside returns → 0.0 (safe for JSON serialization)."""
        dates = pd.date_range("2025-01-01", periods=30, freq="B")
        capitals = [1e6 * (1.001 ** i) for i in range(30)]
        curve = [{"date": str(d.date()), "capital": c} for d, c in zip(dates, capitals)]
        sr = sortino_ratio(curve)
        assert sr == 0.0

    def test_declining_curve(self, declining_curve):
        sr = sortino_ratio(declining_curve)
        assert isinstance(sr, float)


# ---- calmar_ratio ----

class TestCalmarRatio:
    def test_returns_float(self, equity_curve):
        cr = calmar_ratio(equity_curve)
        assert isinstance(cr, float)

    def test_no_drawdown_returns_zero(self):
        curve = [{"date": f"2025-01-{i+1:02d}", "capital": 1e6 + i * 1000} for i in range(20)]
        assert calmar_ratio(curve) == 0.0

    def test_positive_for_profitable_strategy(self, equity_curve):
        cr = calmar_ratio(equity_curve)
        assert cr > 0


# ---- win_rate ----

class TestWinRate:
    def test_known_win_rate(self, sample_trades):
        wr = win_rate(sample_trades)
        assert wr == round(3 / 6 * 100, 2)

    def test_empty_trades(self):
        assert win_rate([]) == 0.0

    def test_all_wins(self):
        trades = [{"profit": 100}, {"profit": 50}]
        assert win_rate(trades) == 100.0

    def test_all_losses(self):
        trades = [{"profit": -100}, {"profit": -50}]
        assert win_rate(trades) == 0.0

    def test_zero_profit_not_win(self):
        trades = [{"profit": 0}]
        assert win_rate(trades) == 0.0

    def test_missing_profit_key(self):
        trades = [{"pnl": 100}]
        assert win_rate(trades) == 0.0


# ---- profit_loss_ratio ----

class TestProfitLossRatio:
    def test_known_ratio(self, sample_trades):
        plr = profit_loss_ratio(sample_trades)
        wins = [500, 300, 800]
        losses = [200, 100, 50]
        expected = round(np.mean(wins) / np.mean(losses), 4)
        assert plr == expected

    def test_empty_trades(self):
        assert profit_loss_ratio([]) == 0.0

    def test_no_wins(self):
        trades = [{"profit": -100}, {"profit": -50}]
        assert profit_loss_ratio(trades) == 0.0

    def test_no_losses(self):
        trades = [{"profit": 100}, {"profit": 50}]
        assert profit_loss_ratio(trades) == 0.0


# ---- monthly_returns ----

class TestMonthlyReturns:
    def test_returns_dataframe(self, equity_curve):
        mr = monthly_returns(equity_curve)
        assert isinstance(mr, pd.DataFrame)

    def test_empty_curve(self):
        mr = monthly_returns([])
        assert mr.empty

    def test_has_monthly_return_column(self, equity_curve):
        mr = monthly_returns(equity_curve)
        assert "monthly_return_pct" in mr.columns

    def test_index_is_monthly(self, equity_curve):
        mr = monthly_returns(equity_curve)
        assert len(mr) > 0


# ---- full_performance_report ----

class TestFullPerformanceReport:
    def test_keys_present(self, equity_curve):
        report = full_performance_report(equity_curve)
        assert "annualized_return_pct" in report
        assert "max_drawdown" in report
        assert "sharpe_ratio" in report
        assert "sortino_ratio" in report
        assert "calmar_ratio" in report

    def test_with_trades(self, equity_curve, sample_trades):
        report = full_performance_report(equity_curve, trades=sample_trades)
        assert "win_rate" in report
        assert "profit_loss_ratio" in report
        assert report["total_trades"] == 6

    def test_without_trades(self, equity_curve):
        report = full_performance_report(equity_curve)
        assert "win_rate" not in report

    def test_empty_curve(self):
        report = full_performance_report([])
        assert report["annualized_return_pct"] == 0.0
        assert report["max_drawdown"]["max_drawdown_pct"] == 0.0
