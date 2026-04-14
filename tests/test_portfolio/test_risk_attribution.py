"""Tests for risk attribution (P1-06)."""
import numpy as np
import pandas as pd
import pytest

from src.portfolio.risk_attribution import STYLE_FACTORS, RiskAttributor


@pytest.fixture()
def synthetic_data():
    """生成 50 只股票的合成截面数据."""
    rng = np.random.default_rng(42)
    n_stocks = 50
    n_days = 60
    stocks = [f"SH60{i:04d}" for i in range(n_stocks)]
    dates = pd.bdate_range("2024-01-01", periods=n_days)

    base = 10.0 + rng.standard_normal(n_stocks) * 2.0
    prices_data = np.zeros((n_days, n_stocks))
    prices_data[0] = np.abs(base) + 5.0
    for t in range(1, n_days):
        prices_data[t] = prices_data[t - 1] * (1.0 + 0.001 + 0.02 * rng.standard_normal(n_stocks))

    prices = pd.DataFrame(prices_data, index=dates, columns=stocks)
    market_caps = pd.Series(rng.uniform(1e8, 1e11, n_stocks), index=stocks)

    industries_list = ["银行", "地产", "科技", "消费", "医药"]
    industries = pd.Series(
        rng.choice(industries_list, n_stocks),
        index=stocks,
    )

    pb_ratios = pd.Series(rng.uniform(0.5, 10.0, n_stocks), index=stocks)
    turnover = pd.Series(rng.uniform(0.5, 5.0, n_stocks), index=stocks)

    returns = prices.iloc[-1] / prices.iloc[-2] - 1.0

    return {
        "prices": prices,
        "market_caps": market_caps,
        "industries": industries,
        "pb_ratios": pb_ratios,
        "turnover": turnover,
        "returns": returns,
        "stocks": stocks,
    }


class TestComputeFactorExposures:
    def test_output_shape(self, synthetic_data):
        attr = RiskAttributor()
        exp = attr.compute_factor_exposures(
            synthetic_data["prices"],
            synthetic_data["market_caps"],
            synthetic_data["industries"],
            synthetic_data["pb_ratios"],
            synthetic_data["turnover"],
        )
        assert exp.shape == (len(synthetic_data["stocks"]), len(STYLE_FACTORS))

    def test_columns_match_style_factors(self, synthetic_data):
        attr = RiskAttributor()
        exp = attr.compute_factor_exposures(
            synthetic_data["prices"],
            synthetic_data["market_caps"],
            synthetic_data["industries"],
            synthetic_data["pb_ratios"],
        )
        assert list(exp.columns) == STYLE_FACTORS

    def test_zscore_properties(self, synthetic_data):
        """z-score 后均值应接近 0, 标准差接近 1."""
        attr = RiskAttributor()
        exp = attr.compute_factor_exposures(
            synthetic_data["prices"],
            synthetic_data["market_caps"],
            synthetic_data["industries"],
            synthetic_data["pb_ratios"],
            synthetic_data["turnover"],
        )
        for col in ["size", "value", "momentum", "volatility"]:
            assert abs(exp[col].mean()) < 0.1
            assert abs(exp[col].std() - 1.0) < 0.15

    def test_no_turnover_liquidity_zero(self, synthetic_data):
        """不传换手率时 liquidity 因子应全为零."""
        attr = RiskAttributor()
        exp = attr.compute_factor_exposures(
            synthetic_data["prices"],
            synthetic_data["market_caps"],
            synthetic_data["industries"],
            synthetic_data["pb_ratios"],
            turnover=None,
        )
        assert (exp["liquidity"] == 0.0).all()


class TestAttributeReturns:
    def _build_dummies(self, industries: pd.Series) -> pd.DataFrame:
        return pd.get_dummies(industries).astype(float)

    def test_output_keys(self, synthetic_data):
        attr = RiskAttributor()
        exp = attr.compute_factor_exposures(
            synthetic_data["prices"],
            synthetic_data["market_caps"],
            synthetic_data["industries"],
            synthetic_data["pb_ratios"],
            synthetic_data["turnover"],
        )
        dummies = self._build_dummies(synthetic_data["industries"])
        result = attr.attribute_returns(synthetic_data["returns"], exp, dummies)
        assert "alpha" in result
        assert "style" in result
        assert "industry" in result
        assert "residual_std" in result
        assert "r_squared" in result

    def test_style_keys_match(self, synthetic_data):
        attr = RiskAttributor()
        exp = attr.compute_factor_exposures(
            synthetic_data["prices"],
            synthetic_data["market_caps"],
            synthetic_data["industries"],
            synthetic_data["pb_ratios"],
        )
        dummies = self._build_dummies(synthetic_data["industries"])
        result = attr.attribute_returns(synthetic_data["returns"], exp, dummies)
        assert set(result["style"].keys()) == set(STYLE_FACTORS)

    def test_r_squared_in_range(self, synthetic_data):
        attr = RiskAttributor()
        exp = attr.compute_factor_exposures(
            synthetic_data["prices"],
            synthetic_data["market_caps"],
            synthetic_data["industries"],
            synthetic_data["pb_ratios"],
            synthetic_data["turnover"],
        )
        dummies = self._build_dummies(synthetic_data["industries"])
        result = attr.attribute_returns(synthetic_data["returns"], exp, dummies)
        assert 0.0 <= result["r_squared"] <= 1.0

    def test_residual_std_non_negative(self, synthetic_data):
        attr = RiskAttributor()
        exp = attr.compute_factor_exposures(
            synthetic_data["prices"],
            synthetic_data["market_caps"],
            synthetic_data["industries"],
            synthetic_data["pb_ratios"],
        )
        dummies = self._build_dummies(synthetic_data["industries"])
        result = attr.attribute_returns(synthetic_data["returns"], exp, dummies)
        assert result["residual_std"] >= 0.0

    def test_insufficient_data_fallback(self):
        """截面样本 < 3 时应安全返回零值."""
        attr = RiskAttributor()
        returns = pd.Series([0.01], index=["A"])
        exp = pd.DataFrame({"size": [0.0]}, index=["A"])
        dummies = pd.DataFrame({"银行": [1.0]}, index=["A"])
        result = attr.attribute_returns(returns, exp, dummies)
        assert result["alpha"] == 0.0
        assert result["r_squared"] == 0.0


class TestGenerateReport:
    def test_report_structure(self, synthetic_data):
        attr = RiskAttributor()
        exp = attr.compute_factor_exposures(
            synthetic_data["prices"],
            synthetic_data["market_caps"],
            synthetic_data["industries"],
            synthetic_data["pb_ratios"],
        )
        dummies = pd.get_dummies(synthetic_data["industries"]).astype(float)
        attribution = attr.attribute_returns(synthetic_data["returns"], exp, dummies)
        report = attr.generate_report(attribution)
        assert "summary" in report
        assert "top_style_factors" in report
        assert "top_industries" in report
        assert "risk_metrics" in report
        assert "r_squared" in report["summary"]
        assert "explained_variance_pct" in report["risk_metrics"]
