"""机构家数 DB / 同步测试。"""
from datetime import date
from unittest.mock import MagicMock, patch

from src.data.inst_holder_store import lookup_latest_batch, upsert_rows


class TestInstHolderStore:

    @patch("src.data.inst_holder_store.get_session")
    def test_upsert_batches(self, mock_gs):
        ctx = MagicMock()
        mock_gs.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)
        n = upsert_rows([{
            "code": "600519",
            "report_date": date(2026, 3, 31),
            "holder_count": 1379,
            "is_complete": True,
            "source": "eastmoney",
        }])
        assert n == 1
        ctx.execute.assert_called_once()

    @patch("src.data.inst_holder_store.get_session")
    def test_lookup_maps_bare_to_qmt(self, mock_gs):
        row = MagicMock()
        row.__getitem__ = lambda self, i: ["600519", date(2026, 3, 31), 1379, "eastmoney", True][i]
        ctx = MagicMock()
        ctx.execute.return_value.fetchall.return_value = [row]
        mock_gs.return_value.__enter__ = MagicMock(return_value=ctx)
        mock_gs.return_value.__exit__ = MagicMock(return_value=False)

        hit = lookup_latest_batch(["600519.SH"], min_year=2026)
        assert hit["600519.SH"]["inst_holder_count"] == 1379
        assert hit["600519.SH"]["inst_holder_source"] == "database"
