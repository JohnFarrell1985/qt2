"""E2E: 绩效统计 + Deflated Sharpe Ratio — 用真实行情构造净值曲线"""
import math

import numpy as np
import pytest

from src.backtest.performance import (
    sharpe_ratio, annualized_return, max_drawdown,
    full_performance_report, deflated_sharpe_ratio, expected_max_sharpe,
)


class TestPerformanceWithRealEquityCurve:
    """用真实日线涨跌幅模拟一个等权持有策略的净值曲线"""

    @pytest.fixture
    def equity_curve(self, real_stock_daily_df):
        df = real_stock_daily_df.sort_values("trade_date").copy()
        df["ret"] = df["close"].pct_change().fillna(0)
        capital = 1_000_000.0
        curve = []
        for _, row in df.iterrows():
            capital *= (1 + row["ret"])
            curve.append({
                "date": row["trade_date"].strftime("%Y-%m-%d"),
                "capital": round(capital, 2),
            })
        return curve

    def test_annualized_return_reasonable(self, equity_curve):
        ann_ret = annualized_return(equity_curve)
        assert -50 < ann_ret < 100, f"Ann return {ann_ret}% out of reasonable range"

    def test_sharpe_ratio_finite(self, equity_curve):
        sr = sharpe_ratio(equity_curve)
        assert not math.isnan(sr)
        assert not math.isinf(sr)

    def test_max_drawdown_nonnegative(self, equity_curve):
        dd = max_drawdown(equity_curve)
        assert dd["max_drawdown_pct"] >= 0
        assert dd["peak_date"] is not None
        assert dd["trough_date"] is not None

    def test_full_report_complete(self, equity_curve):
        report = full_performance_report(equity_curve)
        required_keys = [
            "annualized_return_pct", "max_drawdown",
            "sharpe_ratio", "sortino_ratio", "calmar_ratio",
        ]
        for k in required_keys:
            assert k in report, f"Missing key: {k}"


class TestDeflatedSharpeRatioE2E:
    """用真实净值做 DSR 多重检验修正"""

    @pytest.fixture
    def real_returns(self, real_stock_daily_df):
        df = real_stock_daily_df.sort_values("trade_date").copy()
        return df["close"].pct_change().dropna()

    def test_dsr_returns_probability(self, real_returns):
        sr = float(real_returns.mean() / real_returns.std()) * np.sqrt(252)
        p = deflated_sharpe_ratio(
            sr, num_trials=10,
            var_sharpe=float(real_returns.std() ** 2),
            T=len(real_returns),
        )
        assert 0 <= p <= 1, f"DSR p-value {p} out of [0, 1]"

    def test_more_trials_lower_dsr(self, real_returns):
        sr = float(real_returns.mean() / real_returns.std()) * np.sqrt(252)
        var_sr = float(real_returns.std() ** 2)
        T = len(real_returns)

        p_5 = deflated_sharpe_ratio(sr, 5, var_sr, T=T)
        p_50 = deflated_sharpe_ratio(sr, 50, var_sr, T=T)
        p_500 = deflated_sharpe_ratio(sr, 500, var_sr, T=T)
        assert p_500 <= p_50 <= p_5 + 0.01, (
            f"More trials should yield lower DSR: p5={p_5:.4f}, "
            f"p50={p_50:.4f}, p500={p_500:.4f}"
        )

    def test_expected_max_sharpe_increases_with_trials(self):
        var_sr = 0.04
        ems_10 = expected_max_sharpe(10, var_sr)
        ems_100 = expected_max_sharpe(100, var_sr)
        ems_1000 = expected_max_sharpe(1000, var_sr)
        assert ems_10 < ems_100 < ems_1000

    def test_full_report_with_dsr(self, real_stock_daily_df):
        df = real_stock_daily_df.sort_values("trade_date").copy()
        df["ret"] = df["close"].pct_change().fillna(0)
        capital = 1_000_000.0
        curve = []
        for _, row in df.iterrows():
            capital *= (1 + row["ret"])
            curve.append({
                "date": row["trade_date"].strftime("%Y-%m-%d"),
                "capital": round(capital, 2),
            })

        report = full_performance_report(curve, num_trials=20)
        if report["sharpe_ratio"] != 0:
            assert "deflated_sharpe_pvalue" in report
            assert 0 <= report["deflated_sharpe_pvalue"] <= 1
