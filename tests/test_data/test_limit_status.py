"""涨跌停/停牌状态标注 测试"""
from datetime import date
from unittest.mock import patch, MagicMock

from src.data.limit_status import _get_limit_threshold, calc_limit_status


class TestGetLimitThreshold:
    def test_main_board(self):
        assert _get_limit_threshold("000001.SZ") == 10.0
        assert _get_limit_threshold("600000.SH") == 10.0

    def test_star_market(self):
        assert _get_limit_threshold("688001.SH") == 20.0

    def test_chinext(self):
        assert _get_limit_threshold("300001.SZ") == 20.0


class TestCalcLimitStatus:
    @patch("src.data.limit_status.get_session")
    def test_empty_result(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.fetchall.return_value = []
        mock_get_session.return_value = mock_session

        result = calc_limit_status(date(2025, 1, 2))
        assert result.empty

    @patch("src.data.limit_status.get_session")
    def test_limit_up_detection(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.fetchall.return_value = [
            ("000001.SZ", date(2025, 1, 2), 10.0, 11.0, 10.0, 11.0,
             10.0, 1000000, 10.0),
        ]
        mock_get_session.return_value = mock_session

        result = calc_limit_status(date(2025, 1, 2))
        assert len(result) == 1
        assert result.iloc[0]["is_limit_up"] == True  # noqa: E712
        assert result.iloc[0]["is_limit_down"] == False  # noqa: E712

    @patch("src.data.limit_status.get_session")
    def test_suspended_detection(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.fetchall.return_value = [
            ("000001.SZ", date(2025, 1, 2), 10.0, 10.0, 10.0, 10.0,
             10.0, 0, 0.0),
        ]
        mock_get_session.return_value = mock_session

        result = calc_limit_status(date(2025, 1, 2))
        assert len(result) == 1
        assert result.iloc[0]["is_suspended"] == True  # noqa: E712
