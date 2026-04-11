"""板块行情数据采集 (SectorMarketSync) 单元测试"""
from datetime import date
from unittest.mock import patch, MagicMock

import pandas as pd

from src.data.sector_market_data import SectorMarketSync, _safe_float, _safe_str


# ====================================================================
# _safe_float / _safe_str
# ====================================================================

class TestSafeFloat:
    def test_normal(self):
        assert _safe_float({"涨跌幅": 3.5}, "涨跌幅") == 3.5

    def test_none(self):
        assert _safe_float({"涨跌幅": None}, "涨跌幅") is None

    def test_nan(self):
        assert _safe_float({"v": float("nan")}, "v") is None

    def test_missing_key(self):
        assert _safe_float({}, "涨跌幅") is None

    def test_scale(self):
        result = _safe_float({"净流入": 100_000_000}, "净流入", scale=1e-8)
        assert abs(result - 1.0) < 1e-6


class TestSafeStr:
    def test_normal(self):
        assert _safe_str({"领涨股": "平安银行"}, "领涨股") == "平安银行"

    def test_none(self):
        assert _safe_str({"领涨股": None}, "领涨股") is None

    def test_nan(self):
        assert _safe_str({"v": float("nan")}, "v") is None


# ====================================================================
# SectorMarketSync._fetch_sector_names
# ====================================================================

class TestFetchSectorNames:
    def test_success(self):
        df = pd.DataFrame({"板块名称": ["银行", "医药", "电子"]})
        mock_ak = MagicMock()
        mock_ak.stock_board_industry_name_em.return_value = df
        limiter = MagicMock()

        names = SectorMarketSync._fetch_sector_names(mock_ak, limiter)
        assert names == ["银行", "医药", "电子"]
        limiter.acquire.assert_called_once()

    def test_empty_df(self):
        mock_ak = MagicMock()
        mock_ak.stock_board_industry_name_em.return_value = pd.DataFrame()
        limiter = MagicMock()

        names = SectorMarketSync._fetch_sector_names(mock_ak, limiter)
        assert names == []

    def test_api_error(self):
        mock_ak = MagicMock()
        mock_ak.stock_board_industry_name_em.side_effect = Exception("timeout")
        limiter = MagicMock()

        names = SectorMarketSync._fetch_sector_names(mock_ak, limiter)
        assert names == []


# ====================================================================
# SectorMarketSync._map_hist_rows
# ====================================================================

class TestMapHistRows:
    def test_basic_mapping(self):
        df = pd.DataFrame({
            "日期": ["2024-01-02", "2024-01-03"],
            "涨跌幅": [1.5, -0.8],
        })
        rows = SectorMarketSync._map_hist_rows("银行", df)
        assert len(rows) == 2
        assert rows[0]["sector_name"] == "银行"
        assert rows[0]["trade_date"] == date(2024, 1, 2)
        assert rows[0]["change_pct"] == 1.5

    def test_date_object(self):
        df = pd.DataFrame({
            "日期": [date(2024, 1, 2)],
            "涨跌幅": [2.0],
        })
        rows = SectorMarketSync._map_hist_rows("电子", df)
        assert len(rows) == 1
        assert rows[0]["trade_date"] == date(2024, 1, 2)

    def test_empty_df(self):
        df = pd.DataFrame({"日期": [], "涨跌幅": []})
        assert SectorMarketSync._map_hist_rows("银行", df) == []


# ====================================================================
# sync_sector_data (集成 mock)
# ====================================================================

class TestSyncSectorData:
    @patch("src.data.sector_market_data.get_session")
    def test_full_flow(self, mock_get_session):
        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)
        mock_get_session.return_value = mock_session

        sector_df = pd.DataFrame({"板块名称": ["银行"]})
        hist_df = pd.DataFrame({
            "日期": ["2024-01-02"],
            "涨跌幅": [1.2],
        })
        fund_df = pd.DataFrame({
            "名称": ["银行"],
            "今日涨跌幅": [0.5],
            "今日主力净流入-净额": [100_000_000],
            "今日领涨股": ["平安银行"],
        })

        with patch("src.data.sector_market_data._get_limiter") as mock_limiter_fn:
            limiter = MagicMock()
            mock_limiter_fn.return_value = limiter

            mock_ak = MagicMock()
            mock_ak.stock_board_industry_name_em.return_value = sector_df
            mock_ak.stock_board_industry_hist_em.return_value = hist_df
            mock_ak.stock_sector_fund_flow_rank.return_value = fund_df

            with patch.dict("sys.modules", {"akshare": mock_ak}):
                sync = SectorMarketSync()
                total = sync.sync_sector_data()
                assert total >= 1
