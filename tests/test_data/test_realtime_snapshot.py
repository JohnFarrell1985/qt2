"""实时行情快照采集 (RealtimeSnapshotCollector) 单元测试"""
from datetime import datetime
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest

from src.data.realtime_snapshot import (
    RealtimeSnapshotCollector,
    _safe_tick_float,
    _safe_tick_int,
)


# ====================================================================
# _safe_tick_float / _safe_tick_int
# ====================================================================

class TestSafeTickFloat:
    def test_dict(self):
        assert _safe_tick_float({"lastPrice": 10.5}, "lastPrice") == 10.5

    def test_none_value(self):
        assert _safe_tick_float({"lastPrice": None}, "lastPrice") is None

    def test_missing_key(self):
        assert _safe_tick_float({}, "lastPrice") is None

    def test_transform(self):
        result = _safe_tick_float({"x": 5.0}, "x", transform=lambda v: v * 2)
        assert result == 10.0


class TestSafeTickInt:
    def test_dict(self):
        assert _safe_tick_int({"volume": 1000}, "volume") == 1000

    def test_float_value(self):
        assert _safe_tick_int({"volume": 1000.5}, "volume") == 1000

    def test_none(self):
        assert _safe_tick_int({"volume": None}, "volume") is None


# ====================================================================
# RealtimeSnapshotCollector._map_snapshot_rows
# ====================================================================

class TestMapSnapshotRows:
    def test_basic_mapping(self):
        df = pd.DataFrame({
            "代码": ["000001", "600000"],
            "最新价": [15.0, 8.5],
            "涨跌额": [0.3, -0.1],
            "涨跌幅": [2.0, -1.2],
            "成交量": [100000, 200000],
            "成交额": [1500000.0, 1700000.0],
            "振幅": [3.0, 2.5],
            "换手率": [1.5, 0.8],
            "涨速": [0.5, -0.1],
            "5分钟涨跌": [0.3, -0.2],
            "60日涨跌幅": [10.0, -5.0],
            "年初至今涨跌幅": [15.0, -3.0],
            "总市值": [300_000_000_000, 200_000_000_000],
            "流通市值": [250_000_000_000, 180_000_000_000],
            "动态市盈率": [12.5, 6.0],
            "市净率": [1.5, 0.8],
        })
        ts = datetime(2024, 1, 2, 10, 30, 0)
        rows = RealtimeSnapshotCollector._map_snapshot_rows(df, ts)

        assert len(rows) == 2
        assert rows[0]["code"] == "000001"
        assert rows[0]["timestamp"] == ts
        assert rows[0]["price"] == 15.0
        assert rows[0]["volume"] == 100000
        assert rows[0]["market_cap"] == pytest.approx(3000.0)
        assert rows[0]["float_market_cap"] == pytest.approx(2500.0)
        assert rows[0]["pe_dynamic"] == 12.5

    def test_nan_values(self):
        df = pd.DataFrame({
            "代码": ["000001"],
            "最新价": [float("nan")],
            "涨跌额": [None],
        })
        ts = datetime(2024, 1, 2, 10, 0, 0)
        rows = RealtimeSnapshotCollector._map_snapshot_rows(df, ts)
        assert len(rows) == 1
        assert rows[0]["price"] is None

    def test_empty_df(self):
        df = pd.DataFrame()
        rows = RealtimeSnapshotCollector._map_snapshot_rows(df, datetime.now())
        assert rows == []


# ====================================================================
# RealtimeSnapshotCollector._map_qmt_tick_rows
# ====================================================================

class TestMapQmtTickRows:
    def test_basic(self):
        tick_data = {
            "000001.SZ": {"lastPrice": 15.0, "volume": 100000, "amount": 1500000.0},
        }
        ts = datetime(2024, 1, 2, 10, 0)
        rows = RealtimeSnapshotCollector._map_qmt_tick_rows(tick_data, ts)
        assert len(rows) == 1
        assert rows[0]["code"] == "000001"
        assert rows[0]["price"] == 15.0

    def test_empty_tick(self):
        rows = RealtimeSnapshotCollector._map_qmt_tick_rows({}, datetime.now())
        assert rows == []

    def test_none_tick_value(self):
        tick_data = {"000001.SZ": None}
        rows = RealtimeSnapshotCollector._map_qmt_tick_rows(tick_data, datetime.now())
        assert rows == []


# ====================================================================
# collect_snapshot (集成 mock)
# ====================================================================

class TestCollectSnapshot:
    @patch("src.data.realtime_snapshot.get_session")
    def test_success(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        df = pd.DataFrame({
            "代码": ["000001"],
            "最新价": [15.0],
            "涨跌额": [0.3],
            "涨跌幅": [2.0],
            "成交量": [100000],
            "成交额": [1500000.0],
            "振幅": [3.0],
            "换手率": [1.5],
            "涨速": [0.5],
            "5分钟涨跌": [0.3],
            "60日涨跌幅": [10.0],
            "年初至今涨跌幅": [15.0],
            "总市值": [300_000_000_000],
            "流通市值": [250_000_000_000],
            "动态市盈率": [12.5],
            "市净率": [1.5],
        })
        mock_ak = MagicMock()
        mock_ak.stock_zh_a_spot_em.return_value = df

        with patch("src.data.realtime_snapshot._get_limiter") as mock_limiter_fn:
            mock_limiter_fn.return_value = MagicMock()
            with patch.dict("sys.modules", {"akshare": mock_ak}):
                collector = RealtimeSnapshotCollector()
                count = collector.collect_snapshot()
                assert count == 1

    @patch("src.data.realtime_snapshot._get_limiter")
    def test_api_error(self, mock_limiter_fn):
        mock_limiter_fn.return_value = MagicMock()
        mock_ak = MagicMock()
        mock_ak.stock_zh_a_spot_em.side_effect = Exception("timeout")

        with patch.dict("sys.modules", {"akshare": mock_ak}):
            collector = RealtimeSnapshotCollector()
            count = collector.collect_snapshot()
            assert count == 0


# ====================================================================
# cleanup_old_snapshots
# ====================================================================

class TestCleanupOldSnapshots:
    @patch("src.data.realtime_snapshot.get_session")
    def test_cleanup(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_query = MagicMock()
        mock_query.filter.return_value.delete.return_value = 100
        mock_session.query.return_value = mock_query
        mock_get_session.return_value = mock_session

        collector = RealtimeSnapshotCollector()
        deleted = collector.cleanup_old_snapshots(keep_days=3)
        assert deleted == 100


# ====================================================================
# collect_snapshot_qmt (降级测试)
# ====================================================================

class TestCollectSnapshotQmt:
    @patch.object(RealtimeSnapshotCollector, "collect_snapshot", return_value=42)
    def test_fallback_on_import_error(self, mock_fallback):
        with patch.dict("sys.modules", {"src.data.qmt_client": None}):
            collector = RealtimeSnapshotCollector()
            count = collector.collect_snapshot_qmt()
            assert count == 42
            mock_fallback.assert_called_once()
