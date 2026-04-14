"""Purged Walk-Forward Cross-Validation

Implements Purged K-Fold CV from Marcos López de Prado (2018):
  - Purging: removes training samples whose labels overlap test period
  - Embargo: adds buffer after test to prevent lookahead bias

References:
  - Advances in Financial Machine Learning, Ch.7
  - skfolio model selection docs
"""
from datetime import timedelta

import numpy as np
import pandas as pd
from sklearn.model_selection import BaseCrossValidator

from src.common.config import settings


class PurgedTimeSeriesSplit(BaseCrossValidator):
    """Walk-forward CV with purging and embargo for financial time series.

    Parameters
    ----------
    n_splits : int
        Number of test folds.
    purge_days : int
        Days to purge between train and test to avoid label leakage.
    embargo_pct : float
        Fraction of test size to embargo after each test fold.
    """

    def __init__(
        self,
        n_splits: int = settings.ml.cv_n_splits,
        purge_days: int = settings.ml.cv_purge_days,
        embargo_pct: float = settings.ml.cv_embargo_pct,
    ):
        self.n_splits = n_splits
        self.purge_days = purge_days
        self.embargo_pct = embargo_pct

    def split(self, X, y=None, groups=None):
        """Generate purged walk-forward train/test splits.

        Parameters
        ----------
        X : array-like of shape (n_samples, n_features)
            Feature matrix.
        y : ignored
        groups : array-like of shape (n_samples,)
            Date for each sample (pd.Timestamp or datetime-like). Required.

        Yields
        ------
        train_indices : np.ndarray
        test_indices : np.ndarray
        """
        if groups is None:
            raise ValueError("groups (dates) must be provided for PurgedTimeSeriesSplit")

        dates = pd.Series(pd.to_datetime(groups)).reset_index(drop=True)
        unique_dates = np.sort(dates.unique())
        n_dates = len(unique_dates)

        if n_dates < self.n_splits + 1:
            raise ValueError(
                f"Need at least {self.n_splits + 1} unique dates, got {n_dates}"
            )

        fold_boundaries = np.array_split(np.arange(n_dates), self.n_splits + 1)

        for i in range(1, self.n_splits + 1):
            test_date_indices = fold_boundaries[i]
            test_start = unique_dates[test_date_indices[0]]
            test_end = unique_dates[test_date_indices[-1]]

            purge_delta = timedelta(days=self.purge_days)
            train_end = test_start - purge_delta

            test_size = len(test_date_indices)
            embargo_days = int(np.ceil(test_size * self.embargo_pct))
            embargo_end_idx = test_date_indices[-1] + embargo_days
            if embargo_end_idx < n_dates:
                embargo_end = unique_dates[embargo_end_idx]
            else:
                embargo_end = unique_dates[-1] + timedelta(days=1)

            train_mask = dates <= train_end
            test_mask = (dates >= test_start) & (dates <= test_end)

            embargo_mask = (dates > test_end) & (dates <= embargo_end)
            train_mask = train_mask & ~embargo_mask

            train_idx = np.where(train_mask)[0]
            test_idx = np.where(test_mask)[0]

            if len(train_idx) == 0 or len(test_idx) == 0:
                continue

            yield train_idx, test_idx

    def get_n_splits(self, X=None, y=None, groups=None):
        return self.n_splits
