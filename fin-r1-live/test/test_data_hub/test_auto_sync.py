"""
Tests for auto_sync.py
"""
import pytest
import asyncio
from datetime import date, timedelta
from unittest.mock import Mock, patch, AsyncMock, MagicMock


class TestAutoSyncManager:
    """Test AutoSyncManager class"""
    
    @pytest.fixture
    def manager(self):
        """Create sync manager"""
        from auto_sync import AutoSyncManager
        return AutoSyncManager()
    
    def test_check_database_status_empty(self, manager):
        """Test checking empty database"""
        mock_session = MagicMock()
        mock_session.query.return_value.count.return_value = 0
        mock_session.query.return_value.order_by.return_value.first.return_value = None
        
        with patch('auto_sync.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            status = manager.check_database_status()
            
            assert status["has_data"] is False
            assert status["need_full_download"] is True
    
    def test_check_database_status_complete(self, manager):
        """Test checking complete database"""
        mock_session = MagicMock()
        mock_session.query.return_value.count.side_effect = [5000, 1000000]
        
        # Setup date queries
        min_date_row = MagicMock()
        min_date_row.trade_date = date(2024, 1, 1)
        
        max_date_row = MagicMock()
        max_date_row.trade_date = date.today()
        
        mock_session.query.return_value.order_by.side_effect = [
            MagicMock(first=MagicMock(return_value=(date(2024, 1, 1),))),
            MagicMock(first=MagicMock(return_value=(date.today(),)))
        ]
        
        with patch('auto_sync.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            status = manager.check_database_status()
            
            assert status["need_full_download"] is False
            assert status["need_incremental"] is False
    
    def test_check_database_status_need_incremental(self, manager):
        """Test checking database needing incremental update"""
        mock_session = MagicMock()
        mock_session.query.return_value.count.side_effect = [5000, 1000000]
        
        # Data up to yesterday
        yesterday = date.today() - timedelta(days=1)
        
        mock_session.query.return_value.order_by.side_effect = [
            MagicMock(first=MagicMock(return_value=(date(2024, 1, 1),))),
            MagicMock(first=MagicMock(return_value=(yesterday,)))
        ]
        
        with patch('auto_sync.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            status = manager.check_database_status()
            
            assert status["need_incremental"] is True
            assert status["missing_days"] == 1
    
    def test_check_database_status_need_full(self, manager):
        """Test checking database needing full download (late start date)"""
        mock_session = MagicMock()
        mock_session.query.return_value.count.side_effect = [5000, 1000000]
        
        # Data starts from March 2024 instead of January
        mock_session.query.return_value.order_by.side_effect = [
            MagicMock(first=MagicMock(return_value=(date(2024, 3, 1),))),
            MagicMock(first=MagicMock(return_value=(date.today(),)))
        ]
        
        with patch('auto_sync.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            status = manager.check_database_status()
            
            assert status["need_full_download"] is True
    
    def test_check_database_status_threshold_exceeded(self, manager):
        """Test threshold exceeded triggers full download"""
        mock_session = MagicMock()
        mock_session.query.return_value.count.side_effect = [5000, 1000000]
        
        # Missing 40 days (over threshold of 30)
        forty_days_ago = date.today() - timedelta(days=40)
        
        mock_session.query.return_value.order_by.side_effect = [
            MagicMock(first=MagicMock(return_value=(date(2024, 1, 1),))),
            MagicMock(first=MagicMock(return_value=(forty_days_ago,)))
        ]
        
        with patch('auto_sync.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            status = manager.check_database_status()
            
            assert status["need_full_download"] is True
            assert status["missing_days"] > 30
    
    def test_check_database_status_error(self, manager):
        """Test handling database check error"""
        with patch('auto_sync.get_db_session', side_effect=Exception("DB Error")):
            status = manager.check_database_status()
            
            assert status["need_full_download"] is True
            assert status["has_data"] is False
    
    @pytest.mark.asyncio
    async def test_run_full_download(self, manager):
        """Test full download execution"""
        stocks = [{"code": "000001", "name": "平安银行", "exchange": "SZ"}]
        
        with patch.object(manager.downloader, 'fetch_stock_list', new_callable=AsyncMock) as mock_fetch, \
             patch.object(manager.downloader, 'download_all_history', new_callable=AsyncMock) as mock_download:
            
            mock_fetch.return_value = stocks
            mock_download.return_value = 1000
            
            with patch('auto_sync.StockDAO.bulk_upsert_stocks'):
                total = await manager.run_full_download()
                
                assert total == 1000
                mock_fetch.assert_called_once()
                mock_download.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_run_incremental_sync(self, manager):
        """Test incremental sync execution"""
        yesterday = date.today() - timedelta(days=1)
        
        status = {
            "max_date": yesterday,
            "today": date.today()
        }
        
        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = [("000001",)]
        
        with patch('auto_sync.get_db_session') as mock_get_session, \
             patch.object(manager.downloader, 'fetch_stock_history', new_callable=AsyncMock) as mock_fetch:
            
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            mock_fetch.return_value = [{"code": "000001", "trade_date": date.today()}]
            
            result = await manager.run_incremental_sync(status)
            
            assert result["updated"] > 0 or result["failed"] > 0
    
    @pytest.mark.asyncio
    async def test_run_incremental_sync_up_to_date(self, manager):
        """Test incremental sync when already up to date"""
        today = date.today()
        
        status = {
            "max_date": today,
            "today": today
        }
        
        result = await manager.run_incremental_sync(status)
        
        assert result["updated"] == 0
        assert result["added"] == 0
    
    @pytest.mark.asyncio
    async def test_run_full(self, manager):
        """Test main run method with full download"""
        with patch.object(manager, 'check_database_status') as mock_check, \
             patch.object(manager, 'run_full_download', new_callable=AsyncMock) as mock_full:
            
            mock_check.return_value = {
                "need_full_download": True,
                "need_incremental": False,
                "total_stocks": 0,
                "total_records": 0,
                "missing_days": 365
            }
            mock_full.return_value = 1000
            
            with patch('auto_sync.init_database'):
                success = await manager.run()
                
                assert success is True
                mock_full.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_run_incremental(self, manager):
        """Test main run method with incremental sync"""
        with patch.object(manager, 'check_database_status') as mock_check, \
             patch.object(manager, 'run_incremental_sync', new_callable=AsyncMock) as mock_incremental:
            
            mock_check.return_value = {
                "need_full_download": False,
                "need_incremental": True,
                "total_stocks": 5000,
                "total_records": 1000000,
                "max_date": date.today() - timedelta(days=1),
                "missing_days": 1
            }
            mock_incremental.return_value = {"updated": 10, "added": 100, "failed": 0}
            
            with patch('auto_sync.init_database'):
                success = await manager.run()
                
                assert success is True
                mock_incremental.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_run_no_action_needed(self, manager):
        """Test main run when no action needed"""
        with patch.object(manager, 'check_database_status') as mock_check:
            mock_check.return_value = {
                "need_full_download": False,
                "need_incremental": False,
                "total_stocks": 5000,
                "total_records": 1000000
            }
            
            with patch('auto_sync.init_database'):
                success = await manager.run()
                
                assert success is True
    
    @pytest.mark.asyncio
    async def test_run_init_failure(self, manager):
        """Test handling init database failure"""
        with patch('auto_sync.init_database', side_effect=Exception("Init failed")):
            success = await manager.run()
            
            assert success is False
    
    @pytest.mark.asyncio
    async def test_run_loop(self, manager):
        """Test continuous run loop"""
        with patch.object(manager, 'run', new_callable=AsyncMock) as mock_run, \
             patch('asyncio.sleep', new_callable=AsyncMock) as mock_sleep:
            
            mock_run.side_effect = [True, True, Exception("Stop")]
            
            # Run loop for a few iterations then stop
            try:
                await manager.run_loop(interval_hours=0.001)  # Very short interval for testing
            except Exception:
                pass
            
            assert mock_run.call_count >= 2


class TestMain:
    """Test main entry point"""
    
    @pytest.mark.asyncio
    async def test_main_status_only(self):
        """Test main with --status flag"""
        from auto_sync import main
        
        with patch('sys.argv', ['auto_sync.py', '--status']), \
             patch('auto_sync.AutoSyncManager') as mock_manager_class:
            
            mock_manager = MagicMock()
            mock_manager.check_database_status.return_value = {"has_data": True}
            mock_manager_class.return_value = mock_manager
            
            main()
            
            mock_manager.check_database_status.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_main_loop_mode(self):
        """Test main with --loop flag"""
        from auto_sync import main
        
        with patch('sys.argv', ['auto_sync.py', '--loop']), \
             patch('auto_sync.AutoSyncManager') as mock_manager_class, \
             patch('asyncio.run') as mock_async_run:
            
            mock_manager = MagicMock()
            mock_manager_class.return_value = mock_manager
            
            main()
            
            mock_async_run.assert_called_once()
    
    def test_main_single_run(self):
        """Test main single run"""
        from auto_sync import main
        
        with patch('sys.argv', ['auto_sync.py']), \
             patch('auto_sync.AutoSyncManager') as mock_manager_class, \
             patch('asyncio.run') as mock_async_run:
            
            mock_manager = MagicMock()
            mock_manager.run.return_value = True
            mock_manager_class.return_value = mock_manager
            
            main()
            
            mock_async_run.assert_called_once()


class TestConstants:
    """Test module constants"""
    
    def test_start_date(self):
        """Test START_DATE constant"""
        from auto_sync import START_DATE
        assert START_DATE == date(2024, 1, 1)
    
    def test_threshold(self):
        """Test FULL_DOWNLOAD_THRESHOLD_DAYS"""
        from auto_sync import FULL_DOWNLOAD_THRESHOLD_DAYS
        assert FULL_DOWNLOAD_THRESHOLD_DAYS == 30
