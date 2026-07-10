"""东财 K 线: max_retries 后熔断并切换腾讯."""
from unittest.mock import MagicMock, patch

import pytest

from src.data import kline_bulk_sync as kb


@pytest.fixture(autouse=True)
def _reset_em_state():
    kb.reset_em_cache()
    yield
    kb.reset_em_cache()


class TestEmPush2hisFailover:
    def test_trip_opens_circuit_and_marks_unhealthy(self):
        kb._trip_em_push2his("connection reset")
        assert kb._em_push2his_circuit_open is True
        assert kb._em_healthy is False

    @patch.object(kb, "_get_em_client")
    @patch.object(kb, "_get_em_limiter")
    @patch.object(kb, "_probe_em", return_value=True)
    def test_em_fetch_kline_trips_after_client_retries_exhausted(
        self, _probe, _limiter, _client,
    ):
        _limiter.return_value.acquire.return_value = None
        _client.return_value.get.side_effect = ConnectionError("closed abruptly")

        rows = kb._em_fetch_kline("1.000001", "20260101", "20260110")

        assert rows == []
        assert kb._em_push2his_circuit_open is True
        assert _client.return_value.get.call_count == 1

    @patch.object(kb, "_qq_fetch_stock", return_value=[{"code": "000001", "trade_date": "2026-01-02"}])
    @patch.object(kb, "_em_fetch_stock", return_value=[])
    @patch.object(kb, "_probe_em", return_value=True)
    def test_web_fetch_stock_falls_back_to_tencent_when_em_empty(
        self, _probe, _em, _qq,
    ):
        rows = kb._web_fetch_stock("000001", "20260101", "20260110")
        assert len(rows) == 1
        _qq.assert_called_once()

    @patch.object(kb, "_qq_fetch_stock", return_value=[{"code": "000001"}])
    @patch.object(kb, "_em_fetch_stock")
    @patch.object(kb, "_probe_em", return_value=True)
    def test_web_fetch_stock_skips_em_when_circuit_open(
        self, _probe, _em, _qq,
    ):
        kb._trip_em_push2his("down")
        rows = kb._web_fetch_stock("000001", "20260101", "20260110")
        assert rows
        _em.assert_not_called()
        _qq.assert_called_once()
