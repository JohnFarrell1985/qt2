"""Tests for src/ml/dataset.py - FactorDataset"""
import numpy as np
import pandas as pd
import pytest
from datetime import date
from unittest.mock import patch, MagicMock


def _make_factor_df(n_dates=20, n_stocks=10, factor_names=None, seed=42):
    """Build a synthetic MultiIndex(trade_date, code) factor DataFrame."""
    rng = np.random.RandomState(seed)
    if factor_names is None:
        factor_names = ["f1", "f2", "f3"]
    dates = pd.bdate_range("2024-01-01", periods=n_dates)
    codes = [f"{i:06d}" for i in range(1, n_stocks + 1)]
    index = pd.MultiIndex.from_product([dates, codes], names=["trade_date", "code"])
    data = {f: rng.randn(len(index)) for f in factor_names}
    return pd.DataFrame(data, index=index)


def _make_returns_series(factor_df, seed=99):
    """Build a forward_return Series aligned with factor_df index."""
    rng = np.random.RandomState(seed)
    return pd.Series(
        rng.randn(len(factor_df)) * 0.01,
        index=factor_df.index,
        name="forward_return",
    )


@pytest.fixture
def mock_deps():
    """Patch get_session and FactorDataManager so no DB or network calls happen."""
    with patch("src.ml.dataset.get_session") as mock_session, \
         patch("src.ml.dataset.FactorDataManager") as MockFDM:
        yield mock_session, MockFDM


class TestBuild:
    def test_build_returns_x_y(self, mock_deps):
        mock_session, MockFDM = mock_deps
        factor_df = _make_factor_df()
        returns = _make_returns_series(factor_df)

        mgr = MockFDM.return_value
        mgr.get_factor_values.return_value = factor_df

        mock_sess = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_sess.execute.return_value = mock_result
        mock_session.return_value.__enter__ = MagicMock(return_value=mock_sess)
        mock_session.return_value.__exit__ = MagicMock(return_value=False)

        from src.ml.dataset import FactorDataset
        ds = FactorDataset.__new__(FactorDataset)
        ds.factor_mgr = mgr
        ds.X = None
        ds.y = None
        ds.dates = None

        with patch.object(ds, "_calc_forward_returns", return_value=returns):
            X, y = ds.build(["f1", "f2", "f3"], ["000001"], date(2024, 1, 1), date(2024, 12, 31))

        assert isinstance(X, pd.DataFrame)
        assert isinstance(y, pd.Series)
        assert X.shape[0] == y.shape[0]
        assert X.shape[1] == 3

    def test_build_empty_factors(self, mock_deps):
        _, MockFDM = mock_deps
        mgr = MockFDM.return_value
        mgr.get_factor_values.return_value = pd.DataFrame()

        from src.ml.dataset import FactorDataset
        ds = FactorDataset.__new__(FactorDataset)
        ds.factor_mgr = mgr
        ds.X = None
        ds.y = None
        ds.dates = None

        X, y = ds.build(["f1"], ["000001"], date(2024, 1, 1), date(2024, 12, 31))
        assert X.empty
        assert len(y) == 0

    def test_build_no_intersection(self, mock_deps):
        _, MockFDM = mock_deps
        dates_a = pd.bdate_range("2024-01-01", periods=5)
        dates_b = pd.bdate_range("2024-06-01", periods=5)
        codes = ["000001"]

        idx_a = pd.MultiIndex.from_product([dates_a, codes], names=["trade_date", "code"])
        idx_b = pd.MultiIndex.from_product([dates_b, codes], names=["trade_date", "code"])

        factor_df = pd.DataFrame({"f1": np.ones(5)}, index=idx_a)
        returns = pd.Series(np.ones(5) * 0.01, index=idx_b, name="forward_return")

        mgr = MockFDM.return_value
        mgr.get_factor_values.return_value = factor_df

        from src.ml.dataset import FactorDataset
        ds = FactorDataset.__new__(FactorDataset)
        ds.factor_mgr = mgr
        ds.X = None
        ds.y = None
        ds.dates = None

        with patch.object(ds, "_calc_forward_returns", return_value=returns):
            X, y = ds.build(["f1"], codes, date(2024, 1, 1), date(2024, 12, 31))

        assert X.empty

    def test_build_fills_nan_in_X(self, mock_deps):
        _, MockFDM = mock_deps
        factor_df = _make_factor_df(n_dates=5, n_stocks=3)
        factor_df.iloc[0, 0] = np.nan
        factor_df.iloc[3, 1] = np.nan
        returns = _make_returns_series(factor_df)

        mgr = MockFDM.return_value
        mgr.get_factor_values.return_value = factor_df

        from src.ml.dataset import FactorDataset
        ds = FactorDataset.__new__(FactorDataset)
        ds.factor_mgr = mgr
        ds.X = None
        ds.y = None
        ds.dates = None

        with patch.object(ds, "_calc_forward_returns", return_value=returns):
            X, y = ds.build(["f1", "f2", "f3"], ["000001"], date(2024, 1, 1), date(2024, 12, 31))

        assert X.isna().sum().sum() == 0

    def test_build_drops_nan_in_y(self, mock_deps):
        _, MockFDM = mock_deps
        factor_df = _make_factor_df(n_dates=5, n_stocks=3)
        returns = _make_returns_series(factor_df)
        returns.iloc[0] = np.nan
        returns.iloc[5] = np.nan

        mgr = MockFDM.return_value
        mgr.get_factor_values.return_value = factor_df

        from src.ml.dataset import FactorDataset
        ds = FactorDataset.__new__(FactorDataset)
        ds.factor_mgr = mgr
        ds.X = None
        ds.y = None
        ds.dates = None

        with patch.object(ds, "_calc_forward_returns", return_value=returns):
            X, y = ds.build(["f1", "f2", "f3"], ["000001"], date(2024, 1, 1), date(2024, 12, 31))

        assert y.notna().all()
        assert len(X) == len(y)


class TestTrainValTestSplit:
    def _build_dataset(self, MockFDM):
        factor_df = _make_factor_df(n_dates=20, n_stocks=5)
        returns = _make_returns_series(factor_df)

        mgr = MockFDM.return_value
        mgr.get_factor_values.return_value = factor_df

        from src.ml.dataset import FactorDataset
        ds = FactorDataset.__new__(FactorDataset)
        ds.factor_mgr = mgr
        ds.X = None
        ds.y = None
        ds.dates = None

        with patch.object(ds, "_calc_forward_returns", return_value=returns):
            ds.build(["f1", "f2", "f3"], ["000001"], date(2024, 1, 1), date(2024, 12, 31))
        return ds

    def test_split_keys(self, mock_deps):
        _, MockFDM = mock_deps
        ds = self._build_dataset(MockFDM)
        split = ds.train_val_test_split(train_ratio=0.6, val_ratio=0.2)
        expected_keys = {"X_train", "y_train", "X_val", "y_val",
                         "X_test", "y_test", "train_end", "val_end"}
        assert set(split.keys()) == expected_keys

    def test_split_sizes_non_overlapping(self, mock_deps):
        _, MockFDM = mock_deps
        ds = self._build_dataset(MockFDM)
        split = ds.train_val_test_split(train_ratio=0.6, val_ratio=0.2)

        total = len(split["X_train"]) + len(split["X_val"]) + len(split["X_test"])
        assert total == len(ds.X)
        assert len(split["X_train"]) > 0
        assert len(split["X_val"]) > 0
        assert len(split["X_test"]) > 0

    def test_train_dates_before_val_before_test(self, mock_deps):
        _, MockFDM = mock_deps
        ds = self._build_dataset(MockFDM)
        split = ds.train_val_test_split()

        train_dates = split["X_train"].index.get_level_values("trade_date")
        val_dates = split["X_val"].index.get_level_values("trade_date")
        test_dates = split["X_test"].index.get_level_values("trade_date")

        assert train_dates.max() <= val_dates.min()
        assert val_dates.max() <= test_dates.min()

    def test_split_raises_before_build(self, mock_deps):
        from src.ml.dataset import FactorDataset
        ds = FactorDataset.__new__(FactorDataset)
        ds.X = None
        ds.y = None
        ds.factor_mgr = MagicMock()
        ds.dates = None
        with pytest.raises(ValueError, match="请先调用 build"):
            ds.train_val_test_split()


class TestCalcForwardReturns:
    def test_returns_series_from_db(self, mock_deps):
        mock_get_session, _ = mock_deps

        rows = [
            ("000001", date(2024, 1, 2), 10.0),
            ("000001", date(2024, 1, 3), 10.5),
            ("000001", date(2024, 1, 4), 11.0),
            ("000001", date(2024, 1, 5), 10.8),
            ("000001", date(2024, 1, 8), 11.2),
            ("000001", date(2024, 1, 9), 11.5),
            ("000001", date(2024, 1, 10), 11.8),
        ]
        mock_sess = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = rows
        mock_sess.execute.return_value = mock_result
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_sess)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        from src.ml.dataset import FactorDataset
        ds = FactorDataset.__new__(FactorDataset)
        ds.factor_mgr = MagicMock()
        ds.X = None
        ds.y = None
        ds.dates = None

        result = ds._calc_forward_returns(
            ["000001"], date(2024, 1, 2), date(2024, 1, 5), period=2,
        )
        assert isinstance(result, pd.Series)
        assert result.index.names == ["trade_date", "code"]

    def test_empty_rows_returns_empty(self, mock_deps):
        mock_get_session, _ = mock_deps
        mock_sess = MagicMock()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = []
        mock_sess.execute.return_value = mock_result
        mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_sess)
        mock_get_session.return_value.__exit__ = MagicMock(return_value=False)

        from src.ml.dataset import FactorDataset
        ds = FactorDataset.__new__(FactorDataset)
        ds.factor_mgr = MagicMock()
        ds.X = None
        ds.y = None
        ds.dates = None

        result = ds._calc_forward_returns(
            ["000001"], date(2024, 1, 1), date(2024, 1, 31), period=5,
        )
        assert isinstance(result, pd.Series)
        assert len(result) == 0
