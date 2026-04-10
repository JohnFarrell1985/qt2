"""Tests for src/data/download_engine.py"""
import threading
import time
import pytest
from unittest.mock import patch, MagicMock, call


@pytest.fixture
def mock_settings():
    with patch("src.data.download_engine.settings") as m:
        m.download.batch_size = 3
        m.download.batch_pause = 0.01
        m.download.retry_count = 2
        m.download.retry_delay = 0.01
        m.download.download_timeout = 5
        m.download.default_start_1d = "20200101"
        m.download.default_start_1w = "20200101"
        m.download.default_start_5m = "20230101"
        m.download.default_start_15m = "20230101"
        m.download.default_start_30m = "20230101"
        m.download.default_start_1h = "20230101"
        m.download.default_start_1m = "20250101"
        m.download.default_start_tick = "20260301"
        yield m


@pytest.fixture
def mock_client():
    client = MagicMock()

    def _fake_download_history(stock_list, period, start_time, end_time, callback, incrementally):
        if callback:
            total = len(stock_list)
            for i, code in enumerate(stock_list, 1):
                callback({"finished": i, "total": total, "stockcode": code, "message": ""})

    client.download_history_data2.side_effect = _fake_download_history

    def _fake_download_financial(stock_list, table_list, start_time, end_time, callback):
        if callback:
            total = len(stock_list)
            for i in range(1, total + 1):
                callback({"finished": i, "total": total, "stockcode": "", "message": ""})

    client.download_financial_data2.side_effect = _fake_download_financial
    client.get_local_data.return_value = {}
    return client


@pytest.fixture
def engine(mock_settings, mock_client):
    with patch("src.data.download_engine._dl_cfg", mock_settings.download):
        from src.data.download_engine import DownloadEngine
        eng = DownloadEngine(mock_client)
        eng.batch_size = 3
        eng.batch_pause = 0.01
        eng.retry_count = 2
        eng.retry_delay = 0.01
        eng.timeout = 5
        return eng


class TestSplitBatches:

    def test_even_split(self):
        from src.data.download_engine import split_batches
        result = split_batches([1, 2, 3, 4, 5, 6], 3)
        assert result == [[1, 2, 3], [4, 5, 6]]

    def test_uneven_split(self):
        from src.data.download_engine import split_batches
        result = split_batches([1, 2, 3, 4, 5], 3)
        assert result == [[1, 2, 3], [4, 5]]

    def test_single_batch(self):
        from src.data.download_engine import split_batches
        result = split_batches([1, 2], 5)
        assert result == [[1, 2]]

    def test_empty(self):
        from src.data.download_engine import split_batches
        result = split_batches([], 5)
        assert result == []


class TestGetDefaultStart:

    def test_known_period(self, mock_settings):
        mock_map = {
            "1d": "20200101", "1w": "20200101", "1mon": "20200101",
            "5m": "20230101", "15m": "20230101", "30m": "20230101",
            "1h": "20230101", "1m": "20250101", "tick": "20260301",
        }
        with patch("src.data.download_engine._dl_cfg", mock_settings.download), \
             patch("src.data.download_engine.PERIOD_DEFAULT_START", mock_map):
            from src.data.download_engine import get_default_start
            assert get_default_start("1m") == "20250101"
            assert get_default_start("1d") == "20200101"
            assert get_default_start("5m") == "20230101"

    def test_unknown_period_uses_1d_default(self, mock_settings):
        with patch("src.data.download_engine._dl_cfg", mock_settings.download), \
             patch("src.data.download_engine.PERIOD_DEFAULT_START", {}):
            from src.data.download_engine import get_default_start
            assert get_default_start("unknown") == "20200101"


class TestDownloadKline:

    def test_splits_into_batches(self, engine, mock_client):
        stocks = ["A.SH", "B.SH", "C.SZ", "D.SZ", "E.SZ"]
        progress = engine.download_kline(
            stocks, period="1d", start_time="20240101", end_time="20240601",
        )
        assert progress.total_stocks == 5
        assert progress.total_batches == 2
        assert progress.finished_batches == 2
        assert progress.failed_batches == 0
        assert mock_client.download_history_data2.call_count == 2

    def test_callback_fires_per_batch(self, engine, mock_client):
        results = []
        progress = engine.download_kline(
            ["A.SH", "B.SH", "C.SZ"],
            period="1d", start_time="20240101",
            on_batch_done=lambda r: results.append(r),
        )
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].finished_count == 3

    def test_incremental_true_passes_none(self, engine, mock_client):
        engine.download_kline(
            ["A.SH"], period="1d", start_time="20240101", incremental=True,
        )
        _, kwargs = mock_client.download_history_data2.call_args
        assert kwargs["incrementally"] is None

    def test_incremental_false_passes_false(self, engine, mock_client):
        engine.download_kline(
            ["A.SH"], period="1d", start_time="20240101", incremental=False,
        )
        _, kwargs = mock_client.download_history_data2.call_args
        assert kwargs["incrementally"] is False


class TestDownloadKlineRetry:

    def test_retries_on_failure(self, engine, mock_client):
        call_count = {"n": 0}

        def _fail_then_ok(stock_list, period, start_time, end_time, callback, incrementally):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise ConnectionError("timeout")
            if callback:
                for i in range(1, len(stock_list) + 1):
                    callback({"finished": i, "total": len(stock_list), "stockcode": "", "message": ""})

        mock_client.download_history_data2.side_effect = _fail_then_ok
        progress = engine.download_kline(
            ["A.SH"], period="1d", start_time="20240101",
        )
        assert progress.finished_batches == 1
        assert progress.failed_batches == 0
        assert call_count["n"] == 2

    def test_gives_up_after_max_retries(self, engine, mock_client):
        mock_client.download_history_data2.side_effect = ConnectionError("always fail")
        progress = engine.download_kline(
            ["A.SH"], period="1d", start_time="20240101",
        )
        assert progress.failed_batches == 1
        assert mock_client.download_history_data2.call_count == 2


class TestDownloadFinancial:

    def test_basic_financial_download(self, engine, mock_client):
        progress = engine.download_financial(
            ["A.SH", "B.SH", "C.SZ", "D.SZ"],
            table_list=["Balance", "Income"],
        )
        assert progress.total_batches == 2
        assert progress.failed_batches == 0


class TestGetLocalKlineBatched:

    def test_yields_code_df_pairs(self, engine, mock_client):
        mock_df = MagicMock()
        mock_df.empty = False
        mock_client.get_local_data.return_value = {
            "A.SH": mock_df, "B.SH": mock_df,
        }
        pairs = list(engine.get_local_kline_batched(
            ["A.SH", "B.SH"], period="1d", start_time="20240101",
        ))
        assert len(pairs) == 2
        assert pairs[0][0] == "A.SH"

    def test_skips_empty_dfs(self, engine, mock_client):
        empty_df = MagicMock()
        empty_df.empty = True
        mock_client.get_local_data.return_value = {"A.SH": empty_df}
        pairs = list(engine.get_local_kline_batched(["A.SH"], period="1d"))
        assert len(pairs) == 0


class TestDownloadProgress:

    def test_pct_calculation(self):
        from src.data.download_engine import DownloadProgress
        p = DownloadProgress(total_stocks=100, finished_stocks=25)
        assert p.pct == 25.0

    def test_pct_zero_when_empty(self):
        from src.data.download_engine import DownloadProgress
        p = DownloadProgress(total_stocks=0)
        assert p.pct == 0.0
