"""inst_holders Web UI 层测试 (mock 多源)。"""
import time

from src.webui.inst_holders import (
    InstHolderFetchService,
    _na,
    fetch_inst_holders_multi_source,
)


class TestInstHolderFetchService:

    def test_async_fetch(self, monkeypatch):
        monkeypatch.setattr(
            "src.webui.inst_holders.fetch_inst_holders_multi_source",
            lambda codes: (
                {c: {"inst_holder_count": 7, "inst_holder_report_date": "2026-03-31", "inst_holder_source": "database"} for c in codes},
                ["database"],
            ),
        )
        svc = InstHolderFetchService()
        svc.start("u1", "stock", ["600519.SH"])
        for _ in range(50):
            if not svc.status("u1", "stock").get("running"):
                break
            time.sleep(0.05)
        assert svc.result("u1", "stock")["600519.SH"]["inst_holder_source"] == "database"


class TestMultiSourceOrder:

    def test_merge_prefers_database(self, monkeypatch):
        import src.webui.inst_holders as ih

        monkeypatch.setattr(
            ih,
            "SOURCE_STACK",
            [
                ("database", lambda codes: {c: {"inst_holder_count": 10, "inst_holder_report_date": "2026-03-31", "inst_holder_source": "database"} for c in codes}),
                ("eastmoney", lambda codes: {c: {"inst_holder_count": 99, "inst_holder_report_date": "2026-03-31", "inst_holder_source": "eastmoney"} for c in codes}),
            ],
        )
        out, _ = fetch_inst_holders_multi_source(["600519.SH"])
        assert out["600519.SH"]["inst_holder_count"] == 10

    def test_eastmoney_fills_gap(self, monkeypatch):
        import src.webui.inst_holders as ih

        monkeypatch.setattr(
            ih,
            "SOURCE_STACK",
            [
                ("database", lambda codes: {c: _na() for c in codes}),
                ("eastmoney", lambda codes: {c: {"inst_holder_count": 5, "inst_holder_report_date": "2026-03-31", "inst_holder_source": "eastmoney"} for c in codes}),
            ],
        )
        out, done = fetch_inst_holders_multi_source(["600519.SH"])
        assert out["600519.SH"]["inst_holder_count"] == 5
        assert done == ["database", "eastmoney"]
