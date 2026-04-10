"""UniverseManager 测试"""
from datetime import date
from unittest.mock import patch, MagicMock

from src.data.universe_manager import UniverseManager


class TestUniverseManager:
    def setup_method(self):
        self.mgr = UniverseManager()

    @patch("src.data.universe_manager.get_session")
    def test_get_tradable_empty(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.fetchall.return_value = []
        mock_get_session.return_value = mock_session

        codes = self.mgr.get_tradable(date(2025, 6, 1))
        assert codes == []

    @patch("src.data.universe_manager.get_session")
    def test_get_tradable_returns_codes(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_session.execute.return_value.fetchall.return_value = [
            ("000001.SZ",), ("600000.SH",),
        ]
        mock_get_session.return_value = mock_session

        codes = self.mgr.get_tradable(date(2025, 6, 1))
        assert codes == ["000001.SZ", "600000.SH"]
