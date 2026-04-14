"""Tests for src/factor/xt_factor_loader.py"""

import pandas as pd

from src.factor.xt_factor_loader import XtFactorLoader


class TestXtFactorLoaderWithoutXtquant:
    """测试 xtquant 不可用时的安全降级行为"""

    def test_init_does_not_raise(self):
        loader = XtFactorLoader()
        assert isinstance(loader, XtFactorLoader)

    def test_available_is_false(self):
        loader = XtFactorLoader()
        assert loader.available is False

    def test_load_factor_returns_empty(self):
        loader = XtFactorLoader()
        result = loader.load_factor(["000001.SZ"], "factor_growth")
        assert isinstance(result, pd.DataFrame)
        assert result.empty

    def test_download_all_returns_empty(self):
        loader = XtFactorLoader()
        result = loader.download_all(stock_list=["000001.SZ"])
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_custom_categories(self):
        loader = XtFactorLoader(categories=["factor_growth", "factor_risk"])
        assert loader.categories == ["factor_growth", "factor_risk"]

    def test_default_categories_from_config(self):
        loader = XtFactorLoader()
        assert len(loader.categories) > 0
        assert all(isinstance(c, str) for c in loader.categories)

    def test_get_stock_list_returns_empty(self):
        loader = XtFactorLoader()
        result = loader._get_stock_list()
        assert result == []

    def test_load_factor_with_dates(self):
        loader = XtFactorLoader()
        result = loader.load_factor(
            ["000001.SZ"], "factor_growth",
            start_date="20240101", end_date="20240131",
        )
        assert isinstance(result, pd.DataFrame)
        assert result.empty
