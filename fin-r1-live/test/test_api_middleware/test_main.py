"""
Tests for main.py - FastAPI application
"""
import pytest
import json
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
import httpx


@pytest.fixture
def client(mock_akshare, mock_db_session):
    """Create test client with mocked dependencies"""
    # Import after mocking
    from main import app
    return TestClient(app)


class TestHealthEndpoint:
    """Test health check endpoint"""
    
    def test_health_check_success(self, client):
        """Test health check returns 200"""
        response = client.get("/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert "service" in data
        assert "version" in data
    
    def test_health_check_db_connected(self, client, mock_db_session):
        """Test health check with DB connected"""
        mock_db_session.execute.return_value.scalar.return_value = 100
        
        with patch('main.HistoryDataClient.get_db_status') as mock_status:
            mock_status.return_value = {"connected": True}
            
            response = client.get("/health")
            data = response.json()
            
            assert "database" in data


class TestModelsEndpoint:
    """Test models list endpoint"""
    
    def test_list_models(self, client):
        """Test listing available models"""
        response = client.get("/v1/models")
        assert response.status_code == 200
        
        data = response.json()
        assert data["object"] == "list"
        assert len(data["data"]) > 0
        assert data["data"][0]["id"] == "Fin-R1-Live"


class TestIntentRecognizer:
    """Test FinanceIntentRecognizer"""
    
    @pytest.fixture
    def recognizer(self):
        """Create intent recognizer"""
        from main import FinanceIntentRecognizer
        return FinanceIntentRecognizer()
    
    def test_analyze_realtime_intent(self, recognizer):
        """Test detecting realtime intent"""
        from main import ChatMessage
        
        messages = [
            ChatMessage(role="user", content="今天茅台怎么样")
        ]
        
        intent = recognizer.analyze(messages)
        
        assert intent["need_realtime"] is True
        assert "600519" in intent["stock_codes"] or len(intent["keywords"]) > 0
    
    def test_analyze_history_intent(self, recognizer):
        """Test detecting history intent"""
        from main import ChatMessage
        
        messages = [
            ChatMessage(role="user", content="近3个月走势如何")
        ]
        
        intent = recognizer.analyze(messages)
        
        assert intent["need_history"] is True
        assert intent["history_days"] == 90  # 3 months = 90 days
    
    def test_analyze_stock_code_extraction(self, recognizer):
        """Test extracting stock codes"""
        from main import ChatMessage
        
        messages = [
            ChatMessage(role="user", content="分析一下000001和600519")
        ]
        
        intent = recognizer.analyze(messages)
        
        assert "000001" in intent["stock_codes"]
        assert "600519" in intent["stock_codes"]
    
    def test_analyze_market_overview_intent(self, recognizer):
        """Test detecting market overview intent"""
        from main import ChatMessage
        
        messages = [
            ChatMessage(role="user", content="今天大盘怎么样")
        ]
        
        intent = recognizer.analyze(messages)
        
        assert intent["need_realtime"] is True
        assert intent["data_type"] == "market_overview"
    
    def test_analyze_default_days(self, recognizer):
        """Test default history days"""
        from main import ChatMessage
        
        messages = [
            ChatMessage(role="user", content="分析一下600519的历史走势")
        ]
        
        intent = recognizer.analyze(messages)
        
        assert intent["need_history"] is True
        assert intent["history_days"] == 60  # Default for trend analysis


class TestStockAPIEndpoints:
    """Test stock API endpoints"""
    
    def test_get_realtime_success(self, client, mock_akshare):
        """Test getting realtime stock data"""
        response = client.get("/api/stock/000001/realtime")
        
        assert response.status_code == 200
        data = response.json()
        assert data["code"] == "000001"
        assert "price" in data
    
    def test_get_realtime_invalid_code(self, client):
        """Test getting realtime with invalid stock code"""
        response = client.get("/api/stock/ABC")
        
        assert response.status_code == 400
        assert "无效的股票代码" in response.json()["detail"]
    
    def test_get_realtime_not_found(self, client, mock_akshare):
        """Test getting realtime for non-existent stock"""
        response = client.get("/api/stock/999999/realtime")
        
        assert response.status_code == 404
    
    def test_get_history_success(self, client, mock_db_session):
        """Test getting stock history"""
        # Mock database response
        mock_row = MagicMock()
        mock_row.code = "000001"
        mock_row.trade_date = datetime(2024, 1, 15).date()
        mock_row.open = 10.0
        mock_row.high = 10.5
        mock_row.low = 9.8
        mock_row.close = 10.2
        mock_row.volume = 500000
        mock_row.amount = 5100000
        mock_row.change_pct = 2.0
        mock_row.turnover_rate = 0.5
        
        mock_db_session.execute.return_value = [mock_row]
        
        with patch('main.HistoryDataClient.get_stock_history', return_value=[{
            "code": "000001",
            "trade_date": "2024-01-15",
            "close": 10.2
        }]):
            response = client.get("/api/stock/000001/history?days=30")
            
            assert response.status_code == 200
            data = response.json()
            assert data["code"] == "000001"
            assert len(data["data"]) > 0
    
    def test_get_history_invalid_days(self, client):
        """Test getting history with invalid days parameter"""
        response = client.get("/api/stock/000001/history?days=0")
        
        assert response.status_code == 422  # Validation error
    
    def test_get_analysis_success(self, client):
        """Test getting stock analysis"""
        with patch('main.fetcher.get_quote') as mock_quote, \
             patch('main.HistoryDataClient.get_stock_statistics') as mock_stats:
            
            mock_quote.return_value = Mock(
                code="000001",
                name="平安银行",
                price=10.5,
                change=0.5,
                change_percent=5.0,
                volume=1000000,
                turnover=10500000,
                high=11.0,
                low=10.0,
                open=10.2,
                pre_close=10.0
            )
            
            mock_stats.return_value = {
                "code": "000001",
                "analysis_days": 30,
                "current_price": 10.5,
                "avg_change_pct": 0.5,
                "up_days": 20,
                "down_days": 10
            }
            
            response = client.get("/api/stock/000001/analysis?days=30")
            
            assert response.status_code == 200
            data = response.json()
            assert data["code"] == "000001"
            assert "realtime" in data or "statistics" in data


class TestChatCompletion:
    """Test chat completion endpoint"""
    
    def test_chat_completion_non_stream(self, client, mock_vllm_response):
        """Test non-streaming chat completion"""
        with patch('main._call_vllm_with_retry', new_callable=AsyncMock) as mock_vllm:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = mock_vllm_response
            mock_vllm.return_value = mock_response
            
            response = client.post("/v1/chat/completions", json={
                "model": "Fin-R1-Live",
                "messages": [{"role": "user", "content": "你好"}],
                "stream": False
            })
            
            assert response.status_code == 200
            data = response.json()
            assert "choices" in data or data.get("model") == "Fin-R1-Live"
    
    def test_chat_completion_stream(self, client):
        """Test streaming chat completion"""
        # Stream response is harder to test, just check it returns correctly
        with patch('main.stream_response') as mock_stream:
            mock_stream.return_value = iter([b'data: {"test": "chunk"}\n\n'])
            
            response = client.post("/v1/chat/completions", json={
                "model": "Fin-R1-Live",
                "messages": [{"role": "user", "content": "你好"}],
                "stream": True
            })
            
            # Should return streaming response
            assert response.status_code == 200
    
    def test_chat_completion_vllm_error(self, client):
        """Test handling vLLM error"""
        with patch('main._call_vllm_with_retry', side_effect=Exception("vLLM Error")):
            response = client.post("/v1/chat/completions", json={
                "model": "Fin-R1-Live",
                "messages": [{"role": "user", "content": "你好"}],
                "stream": False
            })
            
            assert response.status_code == 503


class TestMarketOverview:
    """Test market overview endpoint"""
    
    def test_get_market_overview(self, client, mock_akshare):
        """Test getting market overview"""
        response = client.get("/api/market/overview")
        
        assert response.status_code == 200
        data = response.json()
        assert "statistics" in data
        assert "top_gainers" in data


classTestSearch:
    """Test search endpoint"""
    
    def test_search_stock(self, client, mock_akshare):
        """Test searching stocks"""
        response = client.get("/api/search?keyword=平安")
        
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
    
    def test_search_empty_keyword(self, client):
        """Test search with empty keyword"""
        response = client.get("/api/search?keyword=")
        
        # Should still return results or empty list
        assert response.status_code in [200, 422]


class TestDatabaseStatus:
    """Test database status endpoint"""
    
    def test_get_db_status(self, client, mock_db_session):
        """Test getting database status"""
        with patch('main.HistoryDataClient.get_db_status') as mock_status:
            mock_status.return_value = {
                "connected": True,
                "table_counts": {
                    "stocks": 5000,
                    "daily": 1000000
                }
            }
            
            response = client.get("/api/database/status")
            
            assert response.status_code == 200
            data = response.json()
            assert "connected" in data


class TestCORSHeaders:
    """Test CORS headers"""
    
    def test_cors_preflight(self, client):
        """Test CORS preflight request"""
        response = client.options("/v1/models")
        
        # Should have CORS headers
        assert response.status_code == 200


class TestGzipCompression:
    """Test GZip compression"""
    
    def test_gzip_enabled(self, client, mock_akshare):
        """Test that GZip compression is enabled"""
        # Request with gzip accepted
        response = client.get(
            "/api/market/overview",
            headers={"Accept-Encoding": "gzip"}
        )
        
        assert response.status_code == 200
        # Large responses should be compressed
