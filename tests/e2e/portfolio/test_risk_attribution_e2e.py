"""E2E: 简化 Barra 风险归因 — 真实 stock_daily + stocks 数据

覆盖:
  P1-06 RiskAttributor: 因子暴露计算 + 横截面 OLS 归因 + 报告生成
"""
import numpy as np
import pandas as pd

from src.portfolio.risk_attribution import RiskAttributor, STYLE_FACTORS


class TestRiskAttributorE2E:
    """RiskAttributor — 真实截面数据"""

    def test_compute_factor_exposures(self, real_stock_cross_section):
        data = real_stock_cross_section
        attr = RiskAttributor()
        exposures = attr.compute_factor_exposures(
            prices=data["prices"],
            market_caps=data["market_caps"],
            industries=data["industries"],
            pb_ratios=data["pb_ratios"],
        )
        assert isinstance(exposures, pd.DataFrame)
        assert list(exposures.columns) == STYLE_FACTORS
        assert exposures.shape[0] == data["prices"].shape[1]
        for col in STYLE_FACTORS:
            vals = exposures[col].dropna()
            if len(vals) > 1:
                assert abs(vals.mean()) < 1.0, f"{col} z-score 均值应接近 0"

    def test_attribute_returns(self, real_stock_cross_section):
        data = real_stock_cross_section
        attr = RiskAttributor()
        exposures = attr.compute_factor_exposures(
            prices=data["prices"],
            market_caps=data["market_caps"],
            industries=data["industries"],
            pb_ratios=data["pb_ratios"],
        )
        stocks = list(data["prices"].columns)
        portfolio_returns = data["prices"].pct_change().iloc[-1].reindex(stocks).fillna(0)
        industry_dummies = pd.get_dummies(data["industries"]).reindex(stocks).fillna(0)

        result = attr.attribute_returns(portfolio_returns, exposures, industry_dummies)
        assert "alpha" in result
        assert "style" in result
        assert "industry" in result
        assert "r_squared" in result
        assert 0.0 <= result["r_squared"] <= 1.0
        assert set(result["style"].keys()) == set(STYLE_FACTORS)

    def test_generate_report(self, real_stock_cross_section):
        data = real_stock_cross_section
        attr = RiskAttributor()
        exposures = attr.compute_factor_exposures(
            prices=data["prices"],
            market_caps=data["market_caps"],
            industries=data["industries"],
            pb_ratios=data["pb_ratios"],
        )
        stocks = list(data["prices"].columns)
        portfolio_returns = data["prices"].pct_change().iloc[-1].reindex(stocks).fillna(0)
        industry_dummies = pd.get_dummies(data["industries"]).reindex(stocks).fillna(0)
        attribution = attr.attribute_returns(portfolio_returns, exposures, industry_dummies)
        report = attr.generate_report(attribution)

        assert "summary" in report
        assert "top_style_factors" in report
        assert "top_industries" in report
        assert "risk_metrics" in report
        assert report["summary"]["r_squared"] >= 0
        assert len(report["top_style_factors"]) <= 5

    def test_full_pipeline_integration(self, real_stock_cross_section):
        """完整管线: 暴露 → 归因 → 报告 一条龙"""
        data = real_stock_cross_section
        attr = RiskAttributor()

        exposures = attr.compute_factor_exposures(
            prices=data["prices"],
            market_caps=data["market_caps"],
            industries=data["industries"],
            pb_ratios=data["pb_ratios"],
        )

        stocks = list(data["prices"].columns)
        ret = data["prices"].pct_change().dropna()
        portfolio_returns = ret.iloc[-1].reindex(stocks).fillna(0)
        industry_dummies = pd.get_dummies(data["industries"]).reindex(stocks).fillna(0)

        attribution = attr.attribute_returns(portfolio_returns, exposures, industry_dummies)
        report = attr.generate_report(attribution)

        assert report["risk_metrics"]["explained_variance_pct"] >= 0
        total_style = report["summary"]["total_style_contribution"]
        assert np.isfinite(total_style)
