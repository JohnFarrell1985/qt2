"""测试 Tier 2 多因子打分引擎"""
from datetime import date
from unittest.mock import patch
import pandas as pd
import numpy as np

from src.strategy.scoring import (
    _zscore,
    _calc_ic,
    MultiFactorScoringStrategy,
    ICWeightedScoringStrategy,
)


class TestZScore:
    def test_normal(self):
        s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        result = _zscore(s)
        assert abs(result.mean()) < 1e-10
        assert abs(result.std() - 1.0) < 0.2

    def test_constant(self):
        s = pd.Series([5.0] * 10)
        result = _zscore(s)
        assert (result == 0).all()

    def test_outlier_clipping(self):
        s = pd.Series([1, 2, 3, 4, 5, 6, 7, 8, 9, 1000])
        result = _zscore(s)
        assert result.max() < 5.0


class TestCalcIC:
    def test_perfect_correlation(self):
        f = pd.Series([1, 2, 3, 4, 5], index=["a", "b", "c", "d", "e"])
        r = pd.Series([0.1, 0.2, 0.3, 0.4, 0.5], index=["a", "b", "c", "d", "e"])
        # Perfect Spearman correlation but need more than 10 items
        f_big = pd.Series(range(20), index=[f"s{i}" for i in range(20)])
        r_big = pd.Series(range(20), index=[f"s{i}" for i in range(20)])
        ic = _calc_ic(f_big, r_big)
        assert ic > 0.95

    def test_insufficient_data(self):
        f = pd.Series([1, 2], index=["a", "b"])
        r = pd.Series([0.1, 0.2], index=["a", "b"])
        assert _calc_ic(f, r) == 0.0


class TestMultiFactorScoringStrategy:
    def test_registration(self):
        from src.strategy.registry import registry
        cls = registry.get("multifactor_equal")
        assert cls is MultiFactorScoringStrategy
        assert cls.tier == "scoring"

    @patch("src.strategy.scoring._load_factor_data")
    def test_generate_signals(self, mock_load):
        np.random.seed(42)
        codes = [f"00000{i}.SZ" for i in range(1, 6)]
        mock_load.return_value = pd.DataFrame(
            np.random.randn(5, 3),
            index=codes,
            columns=["pe", "roe", "momentum"],
        )

        strat = MultiFactorScoringStrategy(config={
            "factor_names": ["pe", "roe", "momentum"],
            "top_n": 3,
        })
        signals = strat.generate_signals(date(2025, 6, 1), codes)

        assert len(signals) == 3
        assert all(s.direction == "buy" for s in signals)
        assert signals[0].score >= signals[1].score

    @patch("src.strategy.scoring._load_factor_data")
    def test_empty_factors(self, mock_load):
        mock_load.return_value = pd.DataFrame()
        strat = MultiFactorScoringStrategy(config={"factor_names": ["pe"]})
        signals = strat.generate_signals(date(2025, 6, 1), ["000001.SZ"])
        assert len(signals) == 0


class TestICWeightedScoringStrategy:
    def test_registration(self):
        from src.strategy.registry import registry
        cls = registry.get("multifactor_ic")
        assert cls is ICWeightedScoringStrategy
        assert cls.tier == "scoring"
