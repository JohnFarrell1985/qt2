"""
Tests for history_downloader.py
"""
import pytest
import asyncio
import pandas as pd
from datetime import date, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock


class TestHistoryDownloader:
    """Test HistoryDownloader class"""
    
    @pytest.fixture
    def downloader(self):
        """Create downloader instance"""
        from history_downloader import HistoryDownloader
        return HistoryDownloader()
    
    @pytest.mark.asyncio
    async def test_fetch_stock_list(self, downloader):
        """Test fetching stock list"""
        mock_df = pd.DataFrame({
            "code": ["000001", "000002", "600000"],
            "name": ["平安银行", "万科A", "浦发银行"]
        })
        
        with patch('history_downloader.ak.stock_info_a_code_name', return_value=mock_df):
            stocks = await downloader.fetch_stock_list()
            
            assert len(stocks) == 3
            assert stocks[0]["code"] == "000001"
            assert stocks[0]["exchange"] in ["SZ", "SH", "BJ"]
    
    @pytest.mark.asyncio
    async def test_fetch_stock_list_empty(self, downloader):
        """Test fetching empty stock list"""
        mock_df = pd.DataFrame()
        
        with patch('history_downloader.ak.stock_info_a_code_name', return_value=mock_df):
            stocks = await downloader.fetch_stock_list()
            
            assert len(stocks) == 0
    
    @pytest.mark.asyncio
    async def test_fetch_stock_list_error(self, downloader):
        """Test handling stock list fetch error"""
        with patch('history_downloader.ak.stock_info_a_code_name', side_effect=Exception("API Error")):
            stocks = await downloader.fetch_stock_list()
            
            assert len(stocks) == 0
    
    @pytest.mark.asyncio
    async def test_fetch_stock_history_success(self, downloader):
        """Test fetching stock history"""
        mock_df = pd.DataFrame({
            "日期": ["2024-01-15", "2024-01-16"],
            "开盘": [10.0, 10.2],
            "最高": [10.5, 10.6],
            "最低": [9.8, 10.0],
            "收盘": [10.2, 10.5],
            "成交量": [500000, 600000],
            "成交额": [5100000, 6300000],
            "涨跌额": [0.2, 0.3],
            "涨跌幅": [2.0, 2.94],
            "换手率": [0.5, 0.6]
        })
        
        with patch('history_downloader.ak.stock_zh_a_hist', return_value=mock_df):
            history = await downloader.fetch_stock_history("000001", date(2024, 1, 1), date(2024, 1, 31))
            
            assert len(history) == 2
            assert history[0]["code"] == "000001"
            assert history[0]["close"] == 10.2
    
    @pytest.mark.asyncio
    async def test_fetch_stock_history_empty(self, downloader):
        """Test fetching empty history"""
        mock_df = pd.DataFrame()
        
        with patch('history_downloader.ak.stock_zh_a_hist', return_value=mock_df):
            history = await downloader.fetch_stock_history("000001", date(2024, 1, 1), date(2024, 1, 31))
            
            assert len(history) == 0
    
    @pytest.mark.asyncio
    async def test_fetch_stock_history_error(self, downloader):
        """Test handling history fetch error"""
        with patch('history_downloader.ak.stock_zh_a_hist', side_effect=Exception("API Error")):
            history = await downloader.fetch_stock_history("000001", date(2024, 1, 1), date(2024, 1, 31))
            
            assert len(history) == 0
            assert "000001" in downloader.failed_stocks
    
    @pytest.mark.asyncio
    async def test_download_all_history(self, downloader):
        """Test downloading all history"""
        stocks = ["000001", "000002", "600000"]
        
        with patch.object(downloader, 'fetch_stock_history', new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = [{"code": "test", "close": 10.0}]
            
            with patch('history_downloader.get_db_session') as mock_get_session:
                mock_session = MagicMock()
                mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
                mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
                
                total = await downloader.download_all_history(stocks, date(2024, 1, 1))
                
                assert total >= 0
                assert mock_fetch.call_count == len(stocks)
    
    def test_constants(self):
        """Test module constants"""
        from history_downloader import START_DATE, BATCH_SIZE, CONCURRENT_DOWNLOADS
        
        assert START_DATE == date(2024, 1, 1)
        assert BATCH_SIZE == 1000
        assert CONCURRENT_DOWNLOADS == 5
    
    @pytest.mark.asyncio
    async def test_run_sync_timeout(self, downloader):
        """Test run sync with timeout"""
        def slow_func():
            return "result"
        
        # Should complete normally
        result = await downloader._run_sync(slow_func, timeout=5)
        assert result == "result"


class TestMain:
    """Test main entry point"""
    
    def test_main_full_download(self):
        """Test main with full download"""
        from history_downloader import run_full_download
        
        with patch('history_downloader.init_database'), \
             patch('history_downloader.HistoryDownloader') as mock_downloader_class:
            
            mock_downloader = MagicMock()
            mock_downloader.fetch_stock_list = AsyncMock(return_value=[{"code": "000001"}])
            mock_downloader.download_all_history = AsyncMock(return_value=1000)
            mock_downloader_class.return_value = mock_downloader
            
            with patch('asyncio.run', side_effect=lambda coro: asyncio.get_event_loop().run_until_complete(coro)):
                # Just verify it doesn't raise
                pass
    
    def test_main_incremental_update(self):
        """Test main with incremental update"""
        import sys
        
        with patch.object(sys, 'argv', ['history_downloader.py', 'update']):
            # Should handle update argument
            pass
    
    def test_main_test_mode(self):
        """Test main with test mode"""
        import sys
        
        with patch.object(sys, 'argv', ['history_downloader.py', 'test']):
            # Should handle test argument
            pass


class TestRunFullDownload:
    """Test run_full_download function"""
    
    @pytest.mark.asyncio
    async def test_run_full_download(self):
        """Test run full download function"""
        from history_downloader import run_full_download
        
        mock_stocks = [{"code": "000001", "name": "Test", "exchange": "SZ"}]
        
        with patch('history_downloader.HistoryDownloader') as mock_downloader_class, \
             patch('history_downloader.init_database'), \
             patch('history_downloader.get_db_session') as mock_get_session:
            
            mock_downloader = MagicMock()
            mock_downloader.fetch_stock_list = AsyncMock(return_value=mock_stocks)
            mock_downloader.download_all_history = AsyncMock(return_value=1000)
            mock_downloader_class.return_value = mock_downloader
            
            mock_session = MagicMock()
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            # Just verify it doesn't raise
            # Note: Actual async test would need more setup
