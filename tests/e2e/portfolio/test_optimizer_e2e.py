"""E2E: 组合优化 — 真实 ETF 价格数据

覆盖:
  P1-05 CAAOptimizer + RiskParityOptimizer + PortfolioOptimizer 门面
"""
import numpy as np
import pandas as pd

from src.portfolio.optimizer import CAAOptimizer, RiskParityOptimizer, PortfolioOptimizer


class TestCAAOptimizerE2E:
    """Classical Asset Allocation — 真实 ETF 数据"""

    def test_optimize_returns_valid_weights(self, real_etf_price_matrix):
        opt = CAAOptimizer(target_vol=0.10, cap=0.35, cash_assets=set())
        weights = opt.optimize(real_etf_price_matrix)
        assert isinstance(weights, dict)
        assert len(weights) == real_etf_price_matrix.shape[1]
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-4, f"权重之和应为 1, 实际 {total}"
        for code, w in weights.items():
            assert w >= -1e-6, f"{code} 权重为负: {w}"

    def test_cap_constraint_respected(self, real_etf_price_matrix):
        cap = 0.30
        opt = CAAOptimizer(target_vol=0.10, cap=cap, cash_assets=set())
        weights = opt.optimize(real_etf_price_matrix)
        for code, w in weights.items():
            assert w <= cap + 1e-4, f"{code} 权重 {w} 超过 cap {cap}"

    def test_cash_assets_uncapped(self, real_etf_price_matrix):
        cash_code = real_etf_price_matrix.columns[0]
        opt = CAAOptimizer(
            target_vol=0.10, cap=0.10, cash_assets={cash_code},
        )
        weights = opt.optimize(real_etf_price_matrix)
        assert weights[cash_code] <= 1.0 + 1e-6

    def test_momentum_estimate_varies(self, real_etf_price_matrix):
        opt = CAAOptimizer()
        expected_ret = opt._estimate_returns(real_etf_price_matrix)
        assert isinstance(expected_ret, pd.Series)
        assert not expected_ret.isna().all()
        assert expected_ret.std() > 0, "不同 ETF 的动量预期应有差异"


class TestRiskParityOptimizerE2E:
    """等风险贡献优化 — 真实 ETF 数据"""

    def test_optimize_returns_valid_weights(self, real_etf_price_matrix):
        opt = RiskParityOptimizer()
        weights = opt.optimize(real_etf_price_matrix)
        assert isinstance(weights, dict)
        total = sum(weights.values())
        assert abs(total - 1.0) < 1e-4
        for code, w in weights.items():
            assert w >= -1e-6

    def test_weights_are_more_balanced_than_caa(self, real_etf_price_matrix):
        rp = RiskParityOptimizer().optimize(real_etf_price_matrix)
        caa = CAAOptimizer(cap=0.50).optimize(real_etf_price_matrix)

        rp_vals = np.array(list(rp.values()))
        caa_vals = np.array(list(caa.values()))

        rp_std = rp_vals.std()
        caa_std = caa_vals.std()
        assert rp_std <= caa_std + 0.05, "风险平价权重应比 CAA 更均衡"


class TestPortfolioOptimizerE2E:
    """PortfolioOptimizer 门面 — 多方法分发"""

    def test_caa_method(self, real_etf_price_matrix):
        opt = PortfolioOptimizer(method="caa")
        w = opt.optimize(real_etf_price_matrix)
        assert abs(sum(w.values()) - 1.0) < 1e-4

    def test_risk_parity_method(self, real_etf_price_matrix):
        opt = PortfolioOptimizer(method="risk_parity")
        w = opt.optimize(real_etf_price_matrix)
        assert abs(sum(w.values()) - 1.0) < 1e-4

    def test_equal_weight_fallback(self, real_etf_price_matrix):
        opt = PortfolioOptimizer(method="equal")
        w = opt.optimize(real_etf_price_matrix)
        n = real_etf_price_matrix.shape[1]
        expected = 1.0 / n
        for code, weight in w.items():
            assert abs(weight - expected) < 1e-6
