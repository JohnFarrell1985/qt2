"""Web UI 数据同步服务测试。"""
from unittest.mock import AsyncMock, patch

import pytest

from src.webui.data_sync import DataSyncService, get_data_sync_service
from src.webui.paper_engine import PaperAccount
from src.webui.quotes import DayBar, QuoteProvider
from src.webui.store import MemoryStore
from src.trading import market_rules


class FakeBars:
    def __init__(self):
        self.bars = {}
        self.days = []

    def add(self, code, date_str, o, h, low, c, pre=0.0):
        qmt = market_rules.normalize_qmt_code(code)
        self.bars.setdefault(date_str, {})[qmt] = DayBar(
            code=qmt, date=date_str, open=o, high=h, low=low, close=c, pre_close=pre or o,
        )
        if date_str not in self.days:
            self.days.append(date_str)
            self.days.sort()

    def get_bar(self, code, date_str):
        qmt = market_rules.normalize_qmt_code(code)
        return self.bars.get(date_str, {}).get(qmt)

    def latest_trading_day(self):
        return self.days[-1] if self.days else None

    def step_trading_day(self, date_str, direction):
        future = [d for d in self.days if (d > date_str if direction == "next" else d < date_str)]
        if not future:
            return None
        return min(future) if direction == "next" else max(future)

    def trading_days(self, start, end):
        return [d for d in self.days if start <= d <= end]


class TestDataSyncService:

    def test_start_rejects_when_running(self):
        svc = DataSyncService()
        svc._status = {"running": True}
        assert svc.start(lambda: {})["ok"] is False

    @patch("src.data.kline_bulk_sync.run", new_callable=AsyncMock)
    def test_run_sync_then_settle(self, mock_run):
        mock_run.side_effect = [50, 80]

        settled = {"root": {"trade_date": "2026-07-11", "latest": "2026-07-11"}}
        svc = DataSyncService()
        assert svc.start(lambda: settled)["ok"] is True

        import time
        deadline = time.time() + 5
        while time.time() < deadline:
            st = svc.status()
            if not st.get("running"):
                break
            time.sleep(0.05)

        st = svc.status()
        assert st["running"] is False
        assert st["etf_rows"] == 50
        assert st["stock_rows"] == 80
        assert st["settled"] == settled
        assert mock_run.call_count == 2

    def test_get_data_sync_service_singleton(self):
        assert get_data_sync_service() is get_data_sync_service()


class TestSettleToLatest:

    @pytest.fixture
    def bars(self):
        fb = FakeBars()
        fb.add("600519.SH", "2026-07-10", o=1700, h=1750, low=1680, c=1720)
        fb.add("600519.SH", "2026-07-11", o=1720, h=1800, low=1710, c=1780)
        fb.add("600519.SH", "2026-07-12", o=1780, h=1790, low=1770, c=1785)
        return fb

    def test_advances_trade_date_to_latest(self, bars, monkeypatch):
        monkeypatch.setattr("src.webui.paper_engine._today_str", lambda: "2026-07-12")
        acct = PaperAccount(
            name="u1", initial_capital=1_000_000.0,
            quote_provider=QuoteProvider(), bar_provider=bars, store=MemoryStore(),
        )
        acct.set_trade_date("2026-07-10")
        r = acct.settle_to_latest()
        assert r["trade_date"] == "2026-07-12"
        assert r["latest"] == "2026-07-12"
        assert r["steps"] == 2
