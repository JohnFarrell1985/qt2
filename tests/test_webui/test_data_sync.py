"""Web UI 日 K 同步 days_back 自动计算。"""
from datetime import date
from unittest.mock import MagicMock, patch

from src.webui.data_sync import compute_sync_days_back


class TestComputeSyncDaysBack:
    @patch("src.webui.data_sync.get_session")
    def test_two_trading_day_gap(self, mock_gs):
        session = MagicMock()
        mock_gs.return_value.__enter__ = MagicMock(return_value=session)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)
        latest = date(2026, 7, 11)  # 4 calendar days before 2026-07-15
        session.execute.return_value.scalar.side_effect = [latest, latest]

        days, latest_s = compute_sync_days_back(
            min_days=3, buffer_days=3, max_days=30,
        )

        assert latest_s == "2026-07-11"
        assert days == 7  # gap 4 + buffer 3

    @patch("src.webui.data_sync.get_session")
    def test_empty_db_uses_max_window(self, mock_gs):
        session = MagicMock()
        mock_gs.return_value.__enter__ = MagicMock(return_value=session)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)
        session.execute.return_value.scalar.side_effect = [None, None]

        days, latest_s = compute_sync_days_back(max_days=30)

        assert latest_s is None
        assert days == 30
