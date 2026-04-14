"""测试动量因子计算"""
import numpy as np
import pandas as pd
import pytest

from src.strategy.etf_rotation.momentum import (
    calc_13612w,
    calc_dual_momentum,
    calc_r2_return,
    score,
)


def _make_prices(n_days: int = 260, codes: list[str] | None = None, trend: float = 0.001) -> pd.DataFrame:
    """生成合成价格数据 — 几何随机游走"""
    codes = codes or ["ETF_A", "ETF_B", "ETF_C"]
    dates = pd.bdate_range("2024-01-01", periods=n_days)
    rng = np.random.RandomState(42)
    data = {}
    for i, code in enumerate(codes):
        daily_returns = 1 + trend * (i + 1) + rng.normal(0, 0.01, n_days)
        data[code] = 100.0 * np.cumprod(daily_returns)
    return pd.DataFrame(data, index=dates)


class TestCalc13612W:
    def test_uptrend_positive(self):
        prices = _make_prices(260, trend=0.002)
        result = calc_13612w(prices)
        assert not result.empty
        assert (result > 0).all(), f"上升趋势应为正: {result.to_dict()}"

    def test_downtrend_negative(self):
        prices = _make_prices(260, trend=-0.002)
        result = calc_13612w(prices)
        assert (result < 0).all(), f"下降趋势应为负: {result.to_dict()}"

    def test_ranking_preserves_order(self):
        prices = _make_prices(260, trend=0.001)
        result = calc_13612w(prices)
        assert result["ETF_C"] > result["ETF_A"], "趋势更强的 ETF 分数更高"

    def test_empty_input(self):
        result = calc_13612w(pd.DataFrame())
        assert result.empty

    def test_short_history_graceful(self):
        prices = _make_prices(10, trend=0.001)
        result = calc_13612w(prices)
        assert len(result) == 3


class TestCalcR2Return:
    def test_perfect_trend(self):
        dates = pd.bdate_range("2024-01-01", periods=30)
        prices = pd.DataFrame({
            "TREND": [100 * 1.005 ** i for i in range(30)],
        }, index=dates)
        result = calc_r2_return(prices, lookback=25)
        assert result["TREND"] > 0, "完美上涨趋势分数应为正"

    def test_noisy_vs_smooth(self):
        n = 50
        dates = pd.bdate_range("2024-01-01", periods=n)
        smooth = [100 * 1.003 ** i for i in range(n)]
        rng = np.random.RandomState(0)
        noisy = [100 * 1.003 ** i * (1 + rng.normal(0, 0.05)) for i in range(n)]
        prices = pd.DataFrame({"SMOOTH": smooth, "NOISY": noisy}, index=dates)
        result = calc_r2_return(prices, lookback=25)
        assert result["SMOOTH"] > result["NOISY"], "平滑趋势 R² 更高"

    def test_insufficient_data(self):
        prices = _make_prices(5)
        result = calc_r2_return(prices, lookback=25)
        assert result.empty

    def test_empty_input(self):
        result = calc_r2_return(pd.DataFrame())
        assert result.empty


class TestCalcDualMomentum:
    def test_positive_return(self):
        prices = _make_prices(260, trend=0.002)
        result = calc_dual_momentum(prices, lookback_months=12)
        assert (result > 0).all()

    def test_negative_return(self):
        prices = _make_prices(260, trend=-0.003)
        result = calc_dual_momentum(prices, lookback_months=6)
        assert (result < 0).all()

    def test_empty_input(self):
        result = calc_dual_momentum(pd.DataFrame())
        assert result.empty

    def test_short_history_fallback(self):
        prices = _make_prices(30, trend=0.002)
        result = calc_dual_momentum(prices, lookback_months=12)
        assert not result.empty


class TestScoreDispatcher:
    def test_13612w(self):
        prices = _make_prices(260)
        result = score(prices, method="13612w")
        assert len(result) == 3

    def test_r2_return(self):
        prices = _make_prices(60)
        result = score(prices, method="r2_return", lookback_days=25)
        assert len(result) == 3

    def test_dual_momentum(self):
        prices = _make_prices(260)
        result = score(prices, method="dual_momentum")
        assert len(result) == 3

    def test_unknown_method(self):
        prices = _make_prices(60)
        with pytest.raises(ValueError, match="未知动量方法"):
            score(prices, method="invalid")
