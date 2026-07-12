"""机构家数同步模块测试。"""
from datetime import date
from unittest.mock import patch

from src.data.inst_holder_sync import sync_report_date


class TestInstHolderSync:

    @patch("src.data.inst_holder_sync.AltDatacollectProgressDAO.is_ok", return_value=True)
    @patch("src.data.inst_holder_sync.count_for_report_date", return_value=5520)
    def test_skip_when_already_ok(self, _cnt, _ok):
        n = sync_report_date(date(2026, 3, 31))
        assert n == 5520

    @patch("src.data.inst_holder_sync.AltDatacollectProgressDAO.mark_ok")
    @patch("src.data.inst_holder_sync.upsert_rows", return_value=2)
    @patch("src.data.inst_holder_sync.fetch_all_for_report_date")
    @patch("src.data.inst_holder_sync.em_total_for_date", return_value=5520)
    @patch("src.data.inst_holder_sync.AltDatacollectProgressDAO.is_ok", return_value=False)
    def test_sync_writes_rows(self, _ok, _total, fetch, upsert, mark):
        fetch.return_value = [
            {"code": "600519", "report_date": date(2026, 3, 31), "holder_count": 1379, "is_complete": True, "source": "eastmoney"},
            {"code": "000001", "report_date": date(2026, 3, 31), "holder_count": 95, "is_complete": True, "source": "eastmoney"},
        ]
        n = sync_report_date(date(2026, 3, 31))
        assert n == 2
        upsert.assert_called_once()
        mark.assert_called_once()
