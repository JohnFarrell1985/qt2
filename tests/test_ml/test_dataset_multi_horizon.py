"""Tests for FactorDataset.build_multi_horizon in src/ml/dataset.py"""
from datetime import date
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def price_data():
    """Synthetic price data for 3 stocks over 30 trading days."""
    dates = pd.bdate_range("2024-01-01", periods=30)
    codes = ["000001", "000002", "000003"]
    rows = []
    rng = np.random.RandomState(42)
    base_prices = {"000001": 10.0, "000002": 20.0, "000003": 30.0}
    for code in codes:
        p = base_prices[code]
        for d in dates:
            p *= 1 + rng.randn() * 0.02
            rows.append({"code": code, "trade_date": d.date(), "close": round(p, 2)})
    return rows


@pytest.fixture
def factor_df():
    """Synthetic factor data matching the price data index."""
    dates = pd.bdate_range("2024-01-01", periods=30)
    codes = ["000001", "000002", "000003"]
    index = pd.MultiIndex.from_product(
        [dates, codes], names=["trade_date", "code"],
    )
    rng = np.random.RandomState(99)
    return pd.DataFrame(
        {"momentum": rng.randn(len(index)), "volatility": rng.randn(len(index))},
        index=index,
    )


class TestBuildMultiHorizon:
    @pytest.mark.timeout(30)
    @patch("src.ml.dataset.preprocess_cross_section", side_effect=lambda df, **kw: df)
    @patch("src.ml.dataset.FactorDataset._load_industry_data")
    @patch("src.ml.dataset.get_session")
    @patch.object(
        __import__("src.ml.dataset", fromlist=["FactorDataManager"]).FactorDataManager,
        "get_factor_values",
    )
    def test_multi_horizon_labels(
        self,
        mock_get_factors,
        mock_get_session,
        mock_load_industry,
        mock_preprocess,
        factor_df,
        price_data,
    ):
        mock_get_factors.return_value = factor_df
        mock_load_industry.return_value = (
            pd.Series({"000001": "银行", "000002": "科技", "000003": "医药"}),
            pd.Series({"000001": 1e8, "000002": 2e8, "000003": 3e8}),
        )

        mock_session = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = price_data
        mock_session.execute.return_value = mock_result
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        from src.ml.dataset import FactorDataset
        ds = FactorDataset()
        ds.factor_mgr = MagicMock()
        ds.factor_mgr.get_factor_values.return_value = factor_df

        horizons = [1, 3, 5, 10, 20]
        X, y_dict = ds.build_multi_horizon(
            factor_names=["momentum", "volatility"],
            stock_pool=["000001", "000002", "000003"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 9),
            horizons=horizons,
        )

        assert isinstance(y_dict, dict)
        for h in horizons:
            assert h in y_dict, f"missing horizon {h}"
            assert isinstance(y_dict[h], pd.Series)

        if not X.empty:
            assert X.shape[1] == 2
            for h in horizons:
                assert len(y_dict[h]) == len(X)

    @pytest.mark.timeout(30)
    def test_empty_factor_data(self):
        from src.ml.dataset import FactorDataset

        ds = FactorDataset()
        ds.factor_mgr = MagicMock()
        ds.factor_mgr.get_factor_values.return_value = pd.DataFrame()

        X, y_dict = ds.build_multi_horizon(
            factor_names=["f1"],
            stock_pool=["000001"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 1),
        )
        assert X.empty
        assert y_dict == {}

    @pytest.mark.timeout(30)
    def test_default_horizons(self):
        from src.ml.dataset import FactorDataset

        ds = FactorDataset()
        ds.factor_mgr = MagicMock()
        ds.factor_mgr.get_factor_values.return_value = pd.DataFrame()

        X, y_dict = ds.build_multi_horizon(
            factor_names=["f1"],
            stock_pool=["000001"],
            start_date=date(2024, 1, 1),
            end_date=date(2024, 2, 1),
            horizons=None,
        )
        assert y_dict == {}
