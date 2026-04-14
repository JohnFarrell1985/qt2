"""Tests for portfolio optimizers (P1-05)."""
import numpy as np
import pandas as pd
import pytest

from src.portfolio.optimizer import (
    CAAOptimizer,
    PortfolioOptimizer,
    RiskParityOptimizer,
)


def _make_price_data(n_assets: int = 5, n_days: int = 252, seed: int = 42) -> pd.DataFrame:
    """生成合成多资产价格序列 (几何布朗运动)."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2024-01-01", periods=n_days)
    assets = [f"ASSET_{i:02d}" for i in range(n_assets)]
    daily_mu = 0.0003
    daily_sigma = 0.015

    prices = np.zeros((n_days, n_assets))
    prices[0] = 100.0
    for t in range(1, n_days):
        returns = daily_mu + daily_sigma * rng.standard_normal(n_assets)
        prices[t] = prices[t - 1] * (1.0 + returns)

    return pd.DataFrame(prices, index=dates, columns=assets)


@pytest.fixture()
def price_data():
    return _make_price_data()


@pytest.fixture()
def short_price_data():
    """不足 2 个月的短数据."""
    return _make_price_data(n_days=30)


class TestCAAOptimizer:
    def test_weights_sum_to_one(self, price_data):
        opt = CAAOptimizer(target_vol=0.15, cap=0.30, cash_assets=[])
        weights = opt.optimize(price_data)
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_all_weights_non_negative(self, price_data):
        opt = CAAOptimizer(target_vol=0.15, cap=0.30, cash_assets=[])
        weights = opt.optimize(price_data)
        for w in weights.values():
            assert w >= -1e-10, f"权重为负: {w}"

    def test_cap_constraint_respected(self, price_data):
        cap = 0.25
        opt = CAAOptimizer(target_vol=0.15, cap=cap, cash_assets=[])
        weights = opt.optimize(price_data)
        for asset, w in weights.items():
            assert w <= cap + 1e-6, f"{asset} 权重 {w:.4f} 超过上限 {cap}"

    def test_cash_asset_uncapped(self, price_data):
        cap = 0.10
        cash = [price_data.columns[0]]
        opt = CAAOptimizer(target_vol=0.05, cap=cap, cash_assets=cash)
        weights = opt.optimize(price_data)
        assert sum(weights.values()) == pytest.approx(1.0, abs=1e-6)

    def test_returns_dict_with_all_assets(self, price_data):
        opt = CAAOptimizer(target_vol=0.15, cap=0.30, cash_assets=[])
        weights = opt.optimize(price_data)
        assert set(weights.keys()) == set(price_data.columns)

    def test_short_data_fallback_equal_weight(self, short_price_data):
        opt = CAAOptimizer(target_vol=0.15, cap=0.30, cash_assets=[])
        weights = opt.optimize(short_price_data)
        expected = 1.0 / len(short_price_data.columns)
        for w in weights.values():
            assert w == pytest.approx(expected, abs=1e-6)


class TestRiskParityOptimizer:
    def test_weights_sum_to_one(self, price_data):
        opt = RiskParityOptimizer()
        weights = opt.optimize(price_data)
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_all_weights_non_negative(self, price_data):
        opt = RiskParityOptimizer()
        weights = opt.optimize(price_data)
        for w in weights.values():
            assert w >= -1e-10

    def test_weights_roughly_balanced(self, price_data):
        """风险平价下, 同质资产权重应接近等权."""
        opt = RiskParityOptimizer()
        weights = opt.optimize(price_data)
        vals = list(weights.values())
        assert max(vals) / max(min(vals), 1e-10) < 5.0

    def test_returns_dict_with_all_assets(self, price_data):
        opt = RiskParityOptimizer()
        weights = opt.optimize(price_data)
        assert set(weights.keys()) == set(price_data.columns)


class TestPortfolioOptimizer:
    def test_dispatch_caa(self, price_data):
        opt = PortfolioOptimizer(method="caa")
        weights = opt.optimize(price_data, target_vol=0.15, cap=0.30, cash_assets=[])
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_dispatch_risk_parity(self, price_data):
        opt = PortfolioOptimizer(method="risk_parity")
        weights = opt.optimize(price_data)
        assert abs(sum(weights.values()) - 1.0) < 1e-6

    def test_dispatch_equal(self, price_data):
        opt = PortfolioOptimizer(method="equal")
        weights = opt.optimize(price_data)
        expected = 1.0 / len(price_data.columns)
        for w in weights.values():
            assert w == pytest.approx(expected, abs=1e-6)

    def test_default_method_from_config(self, price_data):
        opt = PortfolioOptimizer()
        weights = opt.optimize(price_data)
        assert abs(sum(weights.values()) - 1.0) < 1e-6
        assert set(weights.keys()) == set(price_data.columns)
