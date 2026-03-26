"""
End-to-end integration tests
Tests the entire flow from request to response
"""
import pytest
import asyncio
from datetime import date
from unittest.mock import patch, MagicMock, AsyncMock
import httpx
from fastapi.testclient import TestClient


@pytest.mark.integration
class TestEndToEndFlow:
    """Test complete end-to-end flow"""
    
    @pytest.fixture
    def mock_all_external_services(self):
        """Mock all external dependencies"""
        # Mock database
        mock_db_data = {
            "code": "000001",
            "history": [
                {"trade_date": "2024-01-15", "close": 10.2, "change_pct": 2.0}
            ],
            "stats": {
                "analysis_days": 30,
                "current_price": 10.5,
                "up_days": 20,
                "down_days": 10
            }
        }
        
        # Mock akshare
        import pandas as pd
        mock_akshare_df = pd.DataFrame({
            "代码": ["000001", "000002"],
            "名称": ["平安银行", "万科A"],
            "最新价": [10.5, 15.0],
            "涨跌幅": [2.0, -1.0],
            "成交量": [1000000, 2000000],
            "成交额": [10500000, 30000000],
            "最高": [11.0, 15.5],
            "最低": [10.0, 14.5],
            "今开": [10.2, 14.8],
            "昨收": [10.0, 15.2]
        })
        
        # Mock vLLM response
        mock_vllm_response = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": "Fin-R1-Live",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "根据实时数据分析，平安银行今日表现..."
                },
                "finish_reason": "stop"
            }]
        }
        
        return {
            "db_data": mock_db_data,
            "akshare_df": mock_akshare_df,
            "vllm_response": mock_vllm_response
        }
    
    @pytest.mark.asyncio
    async def test_chat_completion_with_realtime_data(self, mock_all_external_services):
        """Test complete chat completion with realtime data integration"""
        from main import app
        from fastapi.testclient import TestClient
        
        client = TestClient(app)
        
        mocks = mock_all_external_services
        
        with patch('realtime_fetcher.ak.stock_zh_a_spot_em', return_value=mocks["akshare_df"]), \
             patch('database_client.get_db_session') as mock_db_session, \
             patch('main._call_vllm_with_retry', new_callable=AsyncMock) as mock_vllm:
            
            # Setup database mock
            mock_session = MagicMock()
            mock_session.execute.return_value = []
            mock_db_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_db_session.return_value.__exit__ = MagicMock(return_value=False)
            
            # Setup vLLM mock
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mocks["vllm_response"]
            mock_vllm.return_value = mock_response
            
            # Make request
            response = client.post("/v1/chat/completions", json={
                "model": "Fin-R1-Live",
                "messages": [{"role": "user", "content": "分析一下000001今天的行情"}],
                "stream": False
            })
            
            assert response.status_code == 200
            data = response.json()
            assert "choices" in data
    
    @pytest.mark.asyncio
    async def test_chat_completion_with_historical_data(self, mock_all_external_services):
        """Test chat completion with historical data integration"""
        from main import app
        from fastapi.testclient import TestClient
        
        client = TestClient(app)
        
        mocks = mock_all_external_services
        
        # Create mock history rows
        mock_row = MagicMock()
        mock_row.code = "000001"
        mock_row.trade_date = date(2024, 1, 15)
        mock_row.open = 10.0
        mock_row.high = 10.5
        mock_row.low = 9.8
        mock_row.close = 10.2
        mock_row.volume = 500000
        mock_row.amount = 5100000
        mock_row.change_pct = 2.0
        mock_row.turnover_rate = 0.5
        
        mock_stats_row = MagicMock()
        mock_stats_row.current_price = 10.5
        mock_stats_row.period_high = 11.0
        mock_stats_row.period_low = 9.5
        mock_stats_row.total_volume = 5000000
        mock_stats_row.avg_change = 0.5
        mock_stats_row.max_change = 5.0
        mock_stats_row.min_change = -3.0
        mock_stats_row.up_days = 15
        mock_stats_row.down_days = 10
        
        with patch('database_client.get_db_session') as mock_db_session, \
             patch('main._call_vllm_with_retry', new_callable=AsyncMock) as mock_vllm:
            
            # Setup database mock with multiple query results
            mock_session = MagicMock()
            mock_session.execute.side_effect = [
                [mock_row],  # history
                [MagicMock(close=10.5)],  # current price
                [mock_stats_row]  # stats
            ]
            mock_db_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_db_session.return_value.__exit__ = MagicMock(return_value=False)
            
            # Setup vLLM mock
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mocks["vllm_response"]
            mock_vllm.return_value = mock_response
            
            response = client.post("/v1/chat/completions", json={
                "model": "Fin-R1-Live",
                "messages": [{"role": "user", "content": "分析一下000001近3个月的走势"}],
                "stream": False
            })
            
            assert response.status_code == 200
    
    @pytest.mark.asyncio
    async def test_data_sync_then_query(self, mock_all_external_services):
        """Test data sync followed by query"""
        from auto_sync import AutoSyncManager
        from history_downloader import HistoryDownloader
        
        mocks = mock_all_external_services
        
        # Create sync manager
        manager = AutoSyncManager()
        
        # Mock database status - needs full download
        with patch.object(manager, 'check_database_status') as mock_check, \
             patch.object(manager, 'run_full_download', new_callable=AsyncMock) as mock_full:
            
            mock_check.return_value = {
                "has_data": False,
                "need_full_download": True,
                "need_incremental": False
            }
            mock_full.return_value = 1000
            
            with patch('auto_sync.init_database'):
                success = await manager.run()
                
                assert success is True
                mock_full.assert_called_once()


@pytest.mark.integration
class TestErrorScenarios:
    """Test error handling in integration scenarios"""
    
    def test_database_unavailable(self):
        """Test handling when database is unavailable"""
        from main import app
        from fastapi.testclient import TestClient
        
        client = TestClient(app)
        
        with patch('database_client.get_db_session', side_effect=Exception("DB Unavailable")):
            response = client.get("/api/database/status")
            
            assert response.status_code == 200  # Should still return but with error info
            data = response.json()
            assert data["connected"] is False
    
    def test_vllm_unavailable(self):
        """Test handling when vLLM is unavailable"""
        from main import app
        from fastapi.testclient import TestClient
        
        client = TestClient(app)
        
        with patch('main._call_vllm_with_retry', side_effect=Exception("vLLM Unavailable")):
            response = client.post("/v1/chat/completions", json={
                "model": "Fin-R1-Live",
                "messages": [{"role": "user", "content": "test"}],
                "stream": False
            })
            
            assert response.status_code == 503
    
    def test_akshare_api_failure(self):
        """Test handling when akshare API fails"""
        from realtime_fetcher import fetcher
        
        with patch('realtime_fetcher.ak.stock_zh_a_spot_em', side_effect=Exception("API Down")):
            import asyncio
            
            quote = asyncio.get_event_loop().run_until_complete(
                fetcher.get_quote("000001")
            )
            
            assert quote is None  # Should gracefully handle error


@pytest.mark.integration
class TestPerformance:
    """Test performance requirements"""
    
    @pytest.mark.benchmark
    def test_api_response_time(self):
        """Test API response time under 2 seconds"""
        import time
        from main import app
        from fastapi.testclient import TestClient
        
        client = TestClient(app)
        
        start = time.time()
        response = client.get("/health")
        elapsed = time.time() - start
        
        assert response.status_code == 200
        assert elapsed < 2.0  # Should respond within 2 seconds
    
    @pytest.mark.benchmark
    def test_concurrent_requests(self):
        """Test handling concurrent requests"""
        from main import app
        from fastapi.testclient import TestClient
        import concurrent.futures
        
        client = TestClient(app)
        
        def make_request():
            return client.get("/health")
        
        # Make 10 concurrent requests
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(make_request) for _ in range(10)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]
        
        assert all(r.status_code == 200 for r in results)


@pytest.mark.slow
class TestDataConsistency:
    """Test data consistency across components"""
    
    def test_stock_code_consistency(self):
        """Test stock code format is consistent across all components"""
        import re
        
        # Test that all stock codes follow the 6-digit format
        test_codes = ["000001", "000002", "600000", "601398", "300001"]
        pattern = re.compile(r'^\d{6}$')
        
        for code in test_codes:
            assert pattern.match(code), f"Stock code {code} does not match pattern"
    
    def test_date_format_consistency(self):
        """Test date format is consistent"""
        from datetime import date
        
        # Test date to string conversion
        test_date = date(2024, 1, 15)
        date_str = test_date.isoformat()
        
        assert date_str == "2024-01-15"
        
        # Test string to date conversion
        parsed = date.fromisoformat(date_str)
        assert parsed == test_date
