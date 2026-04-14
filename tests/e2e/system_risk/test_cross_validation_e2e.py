"""E2E: PurgedTimeSeriesSplit — 用真实 stock_daily 时间序列验证 CV 分割"""
import pandas as pd
import pytest

from src.ml.cross_validation import PurgedTimeSeriesSplit


class TestPurgedCVWithRealTimeSeries:
    """用真实日线数据构建特征矩阵, 验证 purged walk-forward CV"""

    @pytest.fixture
    def feature_matrix(self, real_stock_daily_df):
        """从真实日线构建简单特征: 5日/10日/20日收益率"""
        df = real_stock_daily_df.sort_values("trade_date").copy()
        df["ret_5"] = df["close"].pct_change(5)
        df["ret_10"] = df["close"].pct_change(10)
        df["ret_20"] = df["close"].pct_change(20)
        df["fwd_ret"] = df["close"].shift(-5) / df["close"] - 1
        df = df.dropna().reset_index(drop=True)
        return df

    def test_splits_non_overlapping(self, feature_matrix):
        X = feature_matrix[["ret_5", "ret_10", "ret_20"]].values
        groups = feature_matrix["trade_date"].values

        cv = PurgedTimeSeriesSplit(n_splits=5, purge_days=3, embargo_pct=0.01)
        seen_test_indices = set()

        for train_idx, test_idx in cv.split(X, groups=groups):
            assert len(train_idx) > 0
            assert len(test_idx) > 0
            overlap = set(train_idx) & set(test_idx)
            assert len(overlap) == 0, "Train and test must not overlap"

            test_set = set(test_idx.tolist())
            prev_overlap = seen_test_indices & test_set
            assert len(prev_overlap) == 0, "Test sets across folds must not overlap"
            seen_test_indices |= test_set

    def test_purge_gap_exists(self, feature_matrix):
        """验证 train 最后一天和 test 第一天之间有 >= purge_days 的间隔"""
        X = feature_matrix[["ret_5", "ret_10", "ret_20"]].values
        dates = feature_matrix["trade_date"].values
        purge_days = 5

        cv = PurgedTimeSeriesSplit(n_splits=3, purge_days=purge_days, embargo_pct=0.01)
        for train_idx, test_idx in cv.split(X, groups=dates):
            train_dates = pd.to_datetime(dates[train_idx])
            test_dates = pd.to_datetime(dates[test_idx])
            gap = (test_dates.min() - train_dates.max()).days
            assert gap >= purge_days, (
                f"Purge gap {gap} days < required {purge_days} days"
            )

    def test_train_grows_monotonically(self, feature_matrix):
        """Walk-forward: 每个 fold 的 train 集应递增"""
        X = feature_matrix[["ret_5", "ret_10", "ret_20"]].values
        groups = feature_matrix["trade_date"].values

        cv = PurgedTimeSeriesSplit(n_splits=5, purge_days=3, embargo_pct=0.01)
        train_sizes = []
        for train_idx, test_idx in cv.split(X, groups=groups):
            train_sizes.append(len(train_idx))

        for i in range(1, len(train_sizes)):
            assert train_sizes[i] >= train_sizes[i - 1], (
                f"Train size should grow: fold {i} ({train_sizes[i]}) "
                f"< fold {i-1} ({train_sizes[i-1]})"
            )

    def test_temporal_ordering(self, feature_matrix):
        """Train 的最大日期 < Test 的最小日期 (after purging)"""
        X = feature_matrix[["ret_5", "ret_10", "ret_20"]].values
        dates = feature_matrix["trade_date"].values

        cv = PurgedTimeSeriesSplit(n_splits=4, purge_days=3, embargo_pct=0.02)
        for train_idx, test_idx in cv.split(X, groups=dates):
            train_max = pd.to_datetime(dates[train_idx]).max()
            test_min = pd.to_datetime(dates[test_idx]).min()
            assert train_max < test_min, "Train max date must be < test min date"

    def test_n_splits_matches(self, feature_matrix):
        X = feature_matrix[["ret_5", "ret_10", "ret_20"]].values
        groups = feature_matrix["trade_date"].values
        n = 5

        cv = PurgedTimeSeriesSplit(n_splits=n, purge_days=3, embargo_pct=0.01)
        splits = list(cv.split(X, groups=groups))
        assert len(splits) == n
        assert cv.get_n_splits() == n

    def test_with_realistic_sample_count(self, feature_matrix):
        """真实数据应有足够多的样本 (> 200 交易日)"""
        assert len(feature_matrix) > 200, (
            f"Expected > 200 samples for meaningful CV, got {len(feature_matrix)}"
        )
