"""选股/选基历史 — 单元测试。"""
from datetime import date
from unittest.mock import MagicMock, patch

from src.webui import selection_history as sh


class TestSelectionHistory:

    @patch("src.webui.selection_history.ensure_schema")
    @patch("src.webui.selection_history.get_session")
    def test_save_run_clears_previous_current(self, mock_gs, _ensure):
        ctx = MagicMock()
        mock_gs.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)
        ctx.execute.return_value.fetchone.return_value = (42,)

        rid = sh.save_run(
            "root", "stock", "bull_launch", date(2026, 7, 10),
            {"max_candidates": 50}, [{"code": "600519.SH"}], 12.3,
        )
        assert rid == 42
        assert ctx.execute.call_count == 3  # clear current + insert + trim

    @patch("src.webui.selection_history.ensure_schema")
    @patch("src.webui.selection_history.get_session")
    def test_get_current(self, mock_gs, _ensure):
        row = (1, "stock", "bull_launch", date(2026, 7, 10), {"a": 1}, [{"code": "x"}], 1, 9.0, True, None)
        ctx = MagicMock()
        ctx.execute.return_value.fetchone.return_value = row
        mock_gs.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)

        run = sh.get_current("root", "stock")
        assert run["run_id"] == 1
        assert run["kind"] == "stock"
        assert run["items"][0]["code"] == "x"

    @patch("src.webui.selection_history.ensure_schema")
    @patch("src.webui.selection_history.get_session")
    def test_delete_run(self, mock_gs, _ensure):
        row = (5, "stock", "bull_launch", date(2026, 7, 10), {}, [], 0, 1.0, True, None)
        ctx = MagicMock()
        ctx.execute.return_value.fetchone.side_effect = [row, None]
        mock_gs.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)

        with patch("src.webui.selection_history.get_run") as mock_get:
            mock_get.return_value = {
                "run_id": 5, "kind": "stock", "is_current": True,
                "strategy_id": "bull_launch", "trade_date": "2026-07-10",
                "params": {}, "items": [], "count": 0, "elapsed": 1.0,
            }
            assert sh.delete_run("root", 5) is True
        assert ctx.execute.call_count >= 2
