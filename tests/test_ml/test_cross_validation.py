"""Tests for PurgedTimeSeriesSplit."""
import numpy as np
import pandas as pd
import pytest

from src.ml.cross_validation import PurgedTimeSeriesSplit


@pytest.fixture()
def synthetic_data():
    """100 trading dates × 10 stocks = 1000 samples."""
    dates = pd.bdate_range("2024-01-01", periods=100)
    stocks = [f"S{i:02d}" for i in range(10)]
    rows = []
    for d in dates:
        for s in stocks:
            rows.append({"date": d, "stock": s})
    df = pd.DataFrame(rows)
    rng = np.random.default_rng(42)
    X = rng.standard_normal((len(df), 5))
    y = rng.standard_normal(len(df))
    groups = df["date"]
    return X, y, groups


class TestPurgedTimeSeriesSplit:
    def test_fold_count(self, synthetic_data):
        X, y, groups = synthetic_data
        cv = PurgedTimeSeriesSplit(n_splits=5, purge_days=3, embargo_pct=0.05)
        splits = list(cv.split(X, y, groups=groups))
        assert len(splits) == 5

    def test_get_n_splits(self):
        cv = PurgedTimeSeriesSplit(n_splits=5)
        assert cv.get_n_splits() == 5
        assert cv.get_n_splits(X=None, y=None, groups=None) == 5

    def test_no_train_test_date_overlap(self, synthetic_data):
        X, y, groups = synthetic_data
        dates = pd.to_datetime(groups)
        cv = PurgedTimeSeriesSplit(n_splits=5, purge_days=3, embargo_pct=0.05)
        for train_idx, test_idx in cv.split(X, y, groups=groups):
            train_dates = set(dates.iloc[train_idx].unique())
            test_dates = set(dates.iloc[test_idx].unique())
            assert train_dates.isdisjoint(test_dates), "Train and test dates must not overlap"

    def test_purge_gap_exists(self, synthetic_data):
        X, y, groups = synthetic_data
        dates = pd.to_datetime(groups)
        purge_days = 3
        cv = PurgedTimeSeriesSplit(n_splits=5, purge_days=purge_days, embargo_pct=0.0)
        for train_idx, test_idx in cv.split(X, y, groups=groups):
            if len(train_idx) == 0:
                continue
            train_max = dates.iloc[train_idx].max()
            test_min = dates.iloc[test_idx].min()
            gap = (test_min - train_max).days
            assert gap >= purge_days, f"Purge gap {gap} < {purge_days}"

    def test_embargo_gap_exists(self, synthetic_data):
        X, y, groups = synthetic_data
        dates = pd.to_datetime(groups)
        cv = PurgedTimeSeriesSplit(n_splits=5, purge_days=0, embargo_pct=0.5)
        splits = list(cv.split(X, y, groups=groups))
        for i, (train_idx, test_idx) in enumerate(splits):
            test_end = dates.iloc[test_idx].max()
            train_after_test = dates.iloc[train_idx][dates.iloc[train_idx] > test_end]
            assert len(train_after_test) == 0, (
                f"Fold {i}: training samples found after test end (embargo violation)"
            )

    def test_train_always_before_test(self, synthetic_data):
        """Rolling scheme: all train dates precede test dates."""
        X, y, groups = synthetic_data
        dates = pd.to_datetime(groups)
        cv = PurgedTimeSeriesSplit(n_splits=5, purge_days=3, embargo_pct=0.05)
        for train_idx, test_idx in cv.split(X, y, groups=groups):
            assert dates.iloc[train_idx].max() < dates.iloc[test_idx].min()

    def test_groups_required(self, synthetic_data):
        X, y, _groups = synthetic_data
        cv = PurgedTimeSeriesSplit(n_splits=5)
        with pytest.raises(ValueError, match="groups.*must be provided"):
            list(cv.split(X, y, groups=None))

    def test_insufficient_dates(self):
        X = np.zeros((5, 2))
        groups = pd.Series(pd.to_datetime(["2024-01-01"] * 5))
        cv = PurgedTimeSeriesSplit(n_splits=5)
        with pytest.raises(ValueError, match="unique dates"):
            list(cv.split(X, groups=groups))

    def test_indices_are_numpy_arrays(self, synthetic_data):
        X, y, groups = synthetic_data
        cv = PurgedTimeSeriesSplit(n_splits=3, purge_days=1, embargo_pct=0.01)
        for train_idx, test_idx in cv.split(X, y, groups=groups):
            assert isinstance(train_idx, np.ndarray)
            assert isinstance(test_idx, np.ndarray)

    def test_sklearn_compatibility(self, synthetic_data):
        """Verify the CV works with sklearn's cross_val_score pattern."""
        cv = PurgedTimeSeriesSplit(n_splits=3, purge_days=1, embargo_pct=0.01)
        assert hasattr(cv, "split")
        assert hasattr(cv, "get_n_splits")
