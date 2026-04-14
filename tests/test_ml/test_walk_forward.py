"""Tests for src/ml/walk_forward.py - RollingWalkForward, WalkForwardWindow"""
from datetime import date

import pytest

from src.ml.walk_forward import RollingWalkForward, WalkForwardWindow


class TestWalkForwardWindow:
    def test_dataclass_fields(self):
        w = WalkForwardWindow(
            train_start=date(2020, 1, 1),
            train_end=date(2021, 12, 31),
            val_start=date(2022, 1, 1),
            val_end=date(2022, 6, 30),
            test_start=date(2022, 7, 1),
            test_end=date(2022, 12, 31),
            window_id=0,
        )
        assert w.train_start == date(2020, 1, 1)
        assert w.window_id == 0


class TestGenerateWindows:
    def test_default_24_6_6_step6(self):
        """Default 24+6+6 month windows with step=6 over a known range."""
        wf = RollingWalkForward(
            train_months=24,
            val_months=6,
            test_months=6,
            step_months=6,
            start_date=date(2018, 1, 1),
            end_date=date(2025, 12, 31),
        )
        windows = wf.generate_windows()
        assert len(windows) > 0

        first = windows[0]
        assert first.train_start == date(2018, 1, 1)
        assert first.train_end == date(2019, 12, 31)
        assert first.val_start == date(2020, 1, 1)
        assert first.val_end == date(2020, 6, 30)
        assert first.test_start == date(2020, 7, 1)
        assert first.test_end == date(2020, 12, 31)
        assert first.window_id == 0

    def test_windows_ids_sequential(self):
        wf = RollingWalkForward(
            start_date=date(2018, 1, 1),
            end_date=date(2026, 1, 1),
        )
        windows = wf.generate_windows()
        ids = [w.window_id for w in windows]
        assert ids == list(range(len(windows)))

    def test_test_periods_dont_overlap(self):
        """Test periods of consecutive windows must not overlap."""
        wf = RollingWalkForward(
            train_months=12,
            val_months=3,
            test_months=3,
            step_months=3,
            start_date=date(2018, 1, 1),
            end_date=date(2025, 12, 31),
        )
        windows = wf.generate_windows()
        assert len(windows) >= 2

        for i in range(len(windows) - 1):
            assert windows[i].test_end < windows[i + 1].test_start

    def test_monotonic_date_progression(self):
        """All dates in each window should be monotonically ordered."""
        wf = RollingWalkForward(
            start_date=date(2019, 1, 1),
            end_date=date(2025, 12, 31),
        )
        windows = wf.generate_windows()
        for w in windows:
            assert w.train_start <= w.train_end
            assert w.train_end < w.val_start
            assert w.val_start <= w.val_end
            assert w.val_end < w.test_start
            assert w.test_start <= w.test_end

    def test_train_starts_advance(self):
        """Each window's train_start should be later than the previous one."""
        wf = RollingWalkForward(
            step_months=6,
            start_date=date(2018, 1, 1),
            end_date=date(2026, 1, 1),
        )
        windows = wf.generate_windows()
        for i in range(1, len(windows)):
            assert windows[i].train_start > windows[i - 1].train_start

    def test_no_windows_if_range_too_short(self):
        """If the date range is shorter than train+val+test, no windows generated."""
        wf = RollingWalkForward(
            train_months=24,
            val_months=6,
            test_months=6,
            start_date=date(2024, 1, 1),
            end_date=date(2025, 6, 1),
        )
        windows = wf.generate_windows()
        assert len(windows) == 0

    def test_test_end_within_end_date(self):
        wf = RollingWalkForward(
            start_date=date(2018, 1, 1),
            end_date=date(2025, 12, 31),
        )
        windows = wf.generate_windows()
        for w in windows:
            assert w.test_end <= date(2025, 12, 31)

    def test_custom_small_windows(self):
        """Smaller windows (6+2+2 months) with step=2."""
        wf = RollingWalkForward(
            train_months=6,
            val_months=2,
            test_months=2,
            step_months=2,
            start_date=date(2023, 1, 1),
            end_date=date(2025, 1, 1),
        )
        windows = wf.generate_windows()
        assert len(windows) >= 3

    def test_invalid_months_raises(self):
        with pytest.raises(ValueError, match="positive"):
            RollingWalkForward(train_months=0)
        with pytest.raises(ValueError, match="positive"):
            RollingWalkForward(val_months=-1)


class TestGetResultsDf:
    def test_empty_results(self):
        wf = RollingWalkForward()
        df = wf.get_results_df()
        assert df.empty

    def test_results_df_columns(self):
        wf = RollingWalkForward()
        wf.results = [
            {
                "window_id": 0,
                "test_period": "2022-07-01~2022-12-31",
                "status": "ok",
                "ic_mean": 0.04,
                "icir": 1.1,
                "long_short_return": 0.02,
                "n_samples": 500,
                "elapsed_sec": 3.5,
            }
        ]
        df = wf.get_results_df()
        assert len(df) == 1
        assert "window_id" in df.columns
        assert "ic_mean" in df.columns
