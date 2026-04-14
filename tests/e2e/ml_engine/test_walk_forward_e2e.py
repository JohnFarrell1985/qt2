"""E2E: Rolling Walk-Forward 窗口生成 — 纯日期计算

覆盖:
  P1-02 RollingWalkForward.generate_windows: 窗口边界、不重叠、覆盖区间
  P1-02 WalkForwardWindow: 数据结构完整性
  (run() 方法需要 FactorDataset + DB 因子数据, 此处仅测试窗口逻辑)
"""
from datetime import date

import pytest

from src.ml.walk_forward import RollingWalkForward, WalkForwardWindow


class TestWalkForwardWindowGenerationE2E:
    """Walk-Forward 窗口生成 — 覆盖主要场景"""

    def test_default_params_generate_windows(self):
        wf = RollingWalkForward(
            start_date=date(2020, 1, 1),
            end_date=date(2026, 1, 1),
        )
        windows = wf.generate_windows()
        assert len(windows) >= 3, f"6 年应生成 3+ 窗口, 实际 {len(windows)}"

    def test_window_boundaries_non_overlapping_test(self):
        wf = RollingWalkForward(
            train_months=12, val_months=3, test_months=3, step_months=3,
            start_date=date(2020, 1, 1), end_date=date(2025, 1, 1),
        )
        windows = wf.generate_windows()
        assert len(windows) >= 5

        for i in range(1, len(windows)):
            curr_train_start = windows[i].train_start
            assert curr_train_start > windows[i - 1].train_start, \
                f"窗口 {i} train_start 未前进"

    def test_window_structure_complete(self):
        wf = RollingWalkForward(
            start_date=date(2021, 1, 1), end_date=date(2025, 1, 1),
        )
        windows = wf.generate_windows()
        for w in windows:
            assert isinstance(w, WalkForwardWindow)
            assert w.train_start < w.train_end
            assert w.train_end < w.val_start
            assert w.val_start <= w.val_end
            assert w.val_end < w.test_start
            assert w.test_start <= w.test_end

    def test_train_end_before_val_start(self):
        wf = RollingWalkForward(
            train_months=24, val_months=6, test_months=6,
            start_date=date(2018, 1, 1), end_date=date(2026, 1, 1),
        )
        for w in wf.generate_windows():
            gap = (w.val_start - w.train_end).days
            assert gap >= 0, "验证期应紧接训练期之后"

    def test_test_end_within_bounds(self):
        end = date(2025, 12, 31)
        wf = RollingWalkForward(
            start_date=date(2020, 1, 1), end_date=end,
        )
        for w in wf.generate_windows():
            assert w.test_end <= end

    def test_short_range_produces_fewer_windows(self):
        wf_short = RollingWalkForward(
            start_date=date(2023, 1, 1), end_date=date(2025, 1, 1),
        )
        wf_long = RollingWalkForward(
            start_date=date(2018, 1, 1), end_date=date(2025, 1, 1),
        )
        assert len(wf_short.generate_windows()) < len(wf_long.generate_windows())

    def test_too_short_range_empty(self):
        wf = RollingWalkForward(
            train_months=24, val_months=6, test_months=6,
            start_date=date(2024, 1, 1), end_date=date(2025, 1, 1),
        )
        windows = wf.generate_windows()
        assert len(windows) == 0

    def test_custom_step_months(self):
        wf3 = RollingWalkForward(
            train_months=12, val_months=3, test_months=3, step_months=3,
            start_date=date(2020, 1, 1), end_date=date(2025, 1, 1),
        )
        wf12 = RollingWalkForward(
            train_months=12, val_months=3, test_months=3, step_months=12,
            start_date=date(2020, 1, 1), end_date=date(2025, 1, 1),
        )
        assert len(wf3.generate_windows()) > len(wf12.generate_windows())

    def test_window_ids_sequential(self):
        wf = RollingWalkForward(
            start_date=date(2019, 1, 1), end_date=date(2026, 1, 1),
        )
        windows = wf.generate_windows()
        for i, w in enumerate(windows):
            assert w.window_id == i

    def test_get_results_df_empty_before_run(self):
        wf = RollingWalkForward()
        df = wf.get_results_df()
        assert df.empty

    def test_invalid_params_raise(self):
        with pytest.raises(ValueError):
            RollingWalkForward(train_months=0)
        with pytest.raises(ValueError):
            RollingWalkForward(val_months=-1)
        with pytest.raises(ValueError):
            RollingWalkForward(step_months=0)
