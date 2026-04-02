"""Tests for src/ml/feature_selection.py - FactorSelector"""
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch, MagicMock


def _build_multiindex_data(n_dates=10, n_stocks=30, n_factors=4, seed=42):
    """Build synthetic MultiIndex(trade_date, code) factor + return DataFrames."""
    rng = np.random.RandomState(seed)
    dates = pd.bdate_range("2024-01-01", periods=n_dates)
    codes = [f"{i:06d}" for i in range(1, n_stocks + 1)]
    index = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])
    n = len(index)

    factor_data = {f"factor_{i}": rng.randn(n) for i in range(n_factors)}
    factor_data["factor_2"] = factor_data["factor_0"] * 0.95 + rng.randn(n) * 0.05
    factor_df = pd.DataFrame(factor_data, index=index)

    forward = rng.randn(n) * 0.02
    return_df = pd.DataFrame({"forward_return": forward}, index=index)
    return factor_df, return_df


@pytest.fixture
def factor_return_data():
    return _build_multiindex_data()


@pytest.fixture
def mock_ic_deps():
    """Mock calc_ic_series, calc_icir, group_return_test so tests don't depend on factor_analysis internals."""
    with patch("src.ml.feature_selection.calc_ic_series") as m_ic, \
         patch("src.ml.feature_selection.calc_icir") as m_icir, \
         patch("src.ml.feature_selection.group_return_test") as m_gr:
        yield m_ic, m_icir, m_gr


class TestAnalyzeAll:
    def test_returns_list_of_reports(self, factor_return_data, mock_ic_deps):
        m_ic, m_icir, m_gr = mock_ic_deps
        m_ic.return_value = pd.Series([0.05, 0.03, 0.04])
        m_icir.return_value = 1.2
        m_gr.return_value = {"G1": -0.01, "G5": 0.02, "long_short": 0.03}

        factor_df, return_df = factor_return_data
        from src.ml.feature_selection import FactorSelector
        selector = FactorSelector(factor_df, return_df)
        reports = selector.analyze_all()

        assert isinstance(reports, list)
        assert len(reports) == factor_df.shape[1]
        for r in reports:
            assert "factor_name" in r
            assert "ic_mean" in r
            assert "icir" in r
            assert "ic_positive_ratio" in r
            assert "group_returns" in r

    def test_sorted_by_abs_ic_descending(self, factor_return_data, mock_ic_deps):
        m_ic, m_icir, m_gr = mock_ic_deps
        ic_values = iter([
            pd.Series([0.01, 0.02]),
            pd.Series([0.10, 0.08]),
            pd.Series([-0.05, -0.06]),
            pd.Series([0.03, 0.04]),
        ])
        m_ic.side_effect = lambda *a, **kw: next(ic_values)
        m_icir.return_value = 1.0
        m_gr.return_value = {}

        factor_df, return_df = factor_return_data
        from src.ml.feature_selection import FactorSelector
        selector = FactorSelector(factor_df, return_df)
        reports = selector.analyze_all()

        abs_ics = [abs(r["ic_mean"]) for r in reports]
        assert abs_ics == sorted(abs_ics, reverse=True)

    def test_handles_empty_ic_series(self, factor_return_data, mock_ic_deps):
        m_ic, m_icir, m_gr = mock_ic_deps
        m_ic.return_value = pd.Series([], dtype=float)
        m_icir.return_value = 0.0
        m_gr.return_value = {}

        factor_df, return_df = factor_return_data
        from src.ml.feature_selection import FactorSelector
        selector = FactorSelector(factor_df, return_df)
        reports = selector.analyze_all()

        for r in reports:
            assert r["ic_mean"] is None
            assert r["icir"] is None
            assert r["ic_positive_ratio"] is None

    def test_handles_group_return_exception(self, factor_return_data, mock_ic_deps):
        m_ic, m_icir, m_gr = mock_ic_deps
        m_ic.return_value = pd.Series([0.05])
        m_icir.return_value = 1.0
        m_gr.side_effect = KeyError("missing column")

        factor_df, return_df = factor_return_data
        from src.ml.feature_selection import FactorSelector
        selector = FactorSelector(factor_df, return_df)
        reports = selector.analyze_all()
        for r in reports:
            assert r["group_returns"] == {}


class TestSelectTopFactors:
    def test_selects_top_n(self, factor_return_data, mock_ic_deps):
        m_ic, m_icir, m_gr = mock_ic_deps
        ic_values = iter([
            pd.Series([0.08]), pd.Series([0.10]),
            pd.Series([-0.06]), pd.Series([0.03]),
        ])
        m_ic.side_effect = lambda *a, **kw: next(ic_values)
        m_icir.return_value = 1.0
        m_gr.return_value = {}

        factor_df, return_df = factor_return_data
        from src.ml.feature_selection import FactorSelector
        selector = FactorSelector(factor_df, return_df)
        top = selector.select_top_factors(n=2, min_abs_ic=0.02)
        assert len(top) <= 2
        assert all(isinstance(f, str) for f in top)

    def test_min_abs_ic_filter(self, factor_return_data, mock_ic_deps):
        m_ic, m_icir, m_gr = mock_ic_deps
        ic_values = iter([
            pd.Series([0.005]), pd.Series([0.10]),
            pd.Series([0.001]), pd.Series([0.03]),
        ])
        m_ic.side_effect = lambda *a, **kw: next(ic_values)
        m_icir.return_value = 1.0
        m_gr.return_value = {}

        factor_df, return_df = factor_return_data
        from src.ml.feature_selection import FactorSelector
        selector = FactorSelector(factor_df, return_df)
        top = selector.select_top_factors(n=10, min_abs_ic=0.02)
        assert len(top) == 2

    def test_auto_calls_analyze_if_not_done(self, factor_return_data, mock_ic_deps):
        m_ic, m_icir, m_gr = mock_ic_deps
        m_ic.return_value = pd.Series([0.05])
        m_icir.return_value = 1.0
        m_gr.return_value = {}

        factor_df, return_df = factor_return_data
        from src.ml.feature_selection import FactorSelector
        selector = FactorSelector(factor_df, return_df)
        assert selector._reports == []
        top = selector.select_top_factors(n=10, min_abs_ic=0.01)
        assert len(selector._reports) > 0


class TestCorrelationFilter:
    def test_removes_highly_correlated(self, factor_return_data, mock_ic_deps):
        m_ic, m_icir, m_gr = mock_ic_deps
        ic_values = iter([
            pd.Series([0.10]), pd.Series([0.05]),
            pd.Series([0.08]), pd.Series([0.03]),
        ])
        m_ic.side_effect = lambda *a, **kw: next(ic_values)
        m_icir.return_value = 1.0
        m_gr.return_value = {}

        factor_df, return_df = factor_return_data
        from src.ml.feature_selection import FactorSelector
        selector = FactorSelector(factor_df, return_df)
        selector.analyze_all()

        all_names = list(factor_df.columns)
        filtered = selector.correlation_filter(all_names, threshold=0.7)
        assert "factor_0" in filtered or "factor_2" in filtered
        assert not ("factor_0" in filtered and "factor_2" in filtered)

    def test_empty_input_returns_empty(self, factor_return_data, mock_ic_deps):
        factor_df, return_df = factor_return_data
        from src.ml.feature_selection import FactorSelector
        selector = FactorSelector(factor_df, return_df)
        assert selector.correlation_filter([], threshold=0.7) == []

    def test_high_threshold_keeps_all(self, mock_ic_deps):
        """With uncorrelated factors and threshold=0.99, all are kept."""
        m_ic, m_icir, m_gr = mock_ic_deps
        m_ic.return_value = pd.Series([0.05])
        m_icir.return_value = 1.0
        m_gr.return_value = {}

        rng = np.random.RandomState(123)
        n = 200
        index = pd.MultiIndex.from_product(
            [pd.bdate_range("2024-01-01", periods=10),
             [f"{i:06d}" for i in range(1, 21)]],
            names=["trade_date", "code"],
        )
        factor_df = pd.DataFrame({f"f{i}": rng.randn(n) for i in range(4)}, index=index)
        return_df = pd.DataFrame({"forward_return": rng.randn(n) * 0.02}, index=index)

        from src.ml.feature_selection import FactorSelector
        selector = FactorSelector(factor_df, return_df)
        selector.analyze_all()
        filtered = selector.correlation_filter(list(factor_df.columns), threshold=0.99)
        assert len(filtered) == 4

    def test_empty_sub_dataframe(self, mock_ic_deps):
        """All NaN factors -> sub.empty -> returns original list."""
        factor_df = pd.DataFrame(
            {"f1": [np.nan, np.nan], "f2": [np.nan, np.nan]},
            index=pd.MultiIndex.from_tuples(
                [("2024-01-01", "000001"), ("2024-01-01", "000002")],
                names=["trade_date", "code"],
            ),
        )
        return_df = pd.DataFrame(
            {"forward_return": [0.01, -0.01]}, index=factor_df.index
        )
        from src.ml.feature_selection import FactorSelector
        selector = FactorSelector(factor_df, return_df)
        selector._reports = [{"factor_name": "f1", "ic_mean": 0.05},
                             {"factor_name": "f2", "ic_mean": 0.03}]
        result = selector.correlation_filter(["f1", "f2"], threshold=0.7)
        assert result == ["f1", "f2"]
