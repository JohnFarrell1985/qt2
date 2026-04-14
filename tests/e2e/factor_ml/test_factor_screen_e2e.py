"""E2E: 因子筛选 + 质量门控 — 真实 stock_daily 数据

覆盖:
  P1-21 AutoFactorScreen (IC/ICIR + 衰减 + 相关性去重)
  P1-34 FactorQualityGate (IC + 分层回测 + 单调性)
"""
import numpy as np
import pandas as pd
import pytest

from src.factor.alpha158 import Alpha158Calculator
from src.factor.auto_screen import AutoFactorScreen
from src.factor.quality_gate import FactorQualityGate


def _build_factor_panel(panel_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """从多股面板构建因子矩阵 + 前瞻收益

    Returns:
        factor_matrix: MultiIndex(trade_date, code) × factor_columns
        forward_returns: MultiIndex(trade_date, code) → float
    """
    calc = Alpha158Calculator(windows=[5, 20])
    all_parts = []
    for code, grp in panel_df.groupby("code"):
        grp = grp.sort_values("trade_date").reset_index(drop=True)
        factors = calc.calc(grp)
        factors["code"] = code
        factors["forward_return"] = grp["close"].shift(-5) / grp["close"] - 1
        all_parts.append(factors)

    combined = pd.concat(all_parts, ignore_index=True)
    combined = combined.dropna(subset=["forward_return"])
    combined = combined.set_index(["trade_date", "code"])

    factor_cols = [c for c in calc.factor_names if c in combined.columns]
    factor_matrix = combined[factor_cols].dropna(axis=1, how="all")
    forward_returns = combined["forward_return"]

    common_idx = factor_matrix.index.intersection(forward_returns.index)
    return factor_matrix.loc[common_idx], forward_returns.loc[common_idx]


class TestAutoFactorScreenE2E:
    """三步因子筛选 — 真实多股面板"""

    @pytest.fixture(scope="class")
    def factor_data(self, real_multi_stock_panel):
        return _build_factor_panel(real_multi_stock_panel)

    def test_screen_returns_list(self, factor_data):
        factor_matrix, forward_returns = factor_data
        screener = AutoFactorScreen(
            ic_threshold=0.01,
            icir_threshold=0.1,
            ic_positive_ratio=0.5,
            corr_threshold=0.9,
            decay_halflife_min=5,
        )
        passed = screener.screen(factor_matrix, forward_returns)
        assert isinstance(passed, list)

    def test_screen_filters_some_factors(self, factor_data):
        factor_matrix, forward_returns = factor_data
        total = len(factor_matrix.columns)
        screener = AutoFactorScreen(
            ic_threshold=0.02,
            icir_threshold=0.2,
            ic_positive_ratio=0.55,
            corr_threshold=0.7,
            decay_halflife_min=10,
        )
        passed = screener.screen(factor_matrix, forward_returns)
        assert len(passed) < total, "筛选应过滤掉部分因子"

    def test_strict_screen_returns_fewer(self, factor_data):
        factor_matrix, forward_returns = factor_data
        loose = AutoFactorScreen(
            ic_threshold=0.01, icir_threshold=0.05,
            ic_positive_ratio=0.45, corr_threshold=0.95,
        )
        strict = AutoFactorScreen(
            ic_threshold=0.05, icir_threshold=0.5,
            ic_positive_ratio=0.6, corr_threshold=0.6,
        )
        loose_passed = loose.screen(factor_matrix, forward_returns)
        strict_passed = strict.screen(factor_matrix, forward_returns)
        assert len(strict_passed) <= len(loose_passed)


class TestFactorQualityGateE2E:
    """因子质量门控 — 真实数据 IC + 分层回测"""

    @pytest.fixture(scope="class")
    def gate_data(self, real_multi_stock_panel):
        factor_matrix, forward_returns = _build_factor_panel(real_multi_stock_panel)
        return_df = forward_returns.to_frame("forward_return")
        return factor_matrix, return_df

    def test_evaluate_single_factor(self, gate_data):
        factor_df, return_df = gate_data
        gate = FactorQualityGate()
        col = factor_df.columns[0]
        result = gate.evaluate(factor_df, return_df, col)
        assert isinstance(result, dict)
        assert "factor_name" in result
        assert "ic_mean" in result
        assert "icir" in result
        assert "quantile_spread" in result
        assert "monotonicity" in result
        assert "passed" in result
        assert isinstance(result["passed"], bool)

    def test_evaluate_produces_valid_metrics(self, gate_data):
        factor_df, return_df = gate_data
        gate = FactorQualityGate()
        col = factor_df.columns[0]
        result = gate.evaluate(factor_df, return_df, col)
        if result["ic_mean"] is not None:
            assert -1 <= result["ic_mean"] <= 1
        if result["icir"] is not None:
            assert np.isfinite(result["icir"])
        if result["monotonicity"] is not None:
            assert 0 <= result["monotonicity"] <= 1

    def test_batch_evaluate(self, gate_data):
        factor_df, return_df = gate_data
        gate = FactorQualityGate()
        cols = list(factor_df.columns[:5])
        results = gate.batch_evaluate(factor_df, return_df, factor_cols=cols)
        assert len(results) == len(cols)
        for r in results:
            assert "factor_name" in r
            assert "passed" in r

    def test_strict_criteria_filters_more(self, gate_data):
        factor_df, return_df = gate_data
        loose = FactorQualityGate(criteria={
            "ic_mean_abs": 0.005, "icir_abs": 0.05,
            "quantile_spread": 0.0001, "monotonicity": 0.3,
        })
        strict = FactorQualityGate(criteria={
            "ic_mean_abs": 0.08, "icir_abs": 1.0,
            "quantile_spread": 0.01, "monotonicity": 0.9,
        })
        cols = list(factor_df.columns[:10])
        loose_r = loose.batch_evaluate(factor_df, return_df, factor_cols=cols)
        strict_r = strict.batch_evaluate(factor_df, return_df, factor_cols=cols)
        loose_pass = sum(1 for r in loose_r if r["passed"])
        strict_pass = sum(1 for r in strict_r if r["passed"])
        assert strict_pass <= loose_pass
