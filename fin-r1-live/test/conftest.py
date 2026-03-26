"""
Pytest configuration and shared fixtures
"""
import os
import sys
import asyncio
import pytest
from datetime import datetime, date, timedelta
from typing import Dict, List, Any
from unittest.mock import MagicMock, AsyncMock, patch, Mock

# Add parent directories to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'api-middleware'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'data-hub'))

# Set environment variables for testing
os.environ.setdefault('DATABASE_URL', 'postgresql://test:test@localhost:5432/test_db')
os.environ.setdefault('VLLM_BASE_URL', 'http://localhost:8010')
os.environ.setdefault('LOG_LEVEL', 'DEBUG')
os.environ.setdefault('API_KEY', 'test-key')


@pytest.fixture
def event_loop():
    """Create an event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_stock_quote():
    """Mock stock quote data"""
    return {
        "code": "000001",
        "name": "平安银行",
        "price": 10.5,
        "change": 0.5,
        "change_percent": 5.0,
        "volume": 1000000,
        "turnover": 10500000,
        "high": 11.0,
        "low": 10.0,
        "open": 10.2,
        "pre_close": 10.0,
        "pe": 8.5,
        "pb": 1.2,
        "market_cap": 2000000000
    }


@pytest.fixture
def mock_stock_daily():
    """Mock stock daily data"""
    return {
        "code": "000001",
        "trade_date": date(2024, 1, 15),
        "open": 10.0,
        "high": 10.5,
        "low": 9.8,
        "close": 10.2,
        "volume": 500000,
        "amount": 5100000,
        "change": 0.2,
        "change_pct": 2.0,
        "turnover_rate": 0.5
    }


@pytest.fixture
def mock_market_overview():
    """Mock market overview data"""
    return {
        "update_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "statistics": {
            "up": 2500,
            "down": 2000,
            "flat": 300
        },
        "top_gainers": [
            {"name": "贵州茅台", "change": 10.0},
            {"name": "比亚迪", "change": 9.8}
        ],
        "top_losers": [
            {"name": "某某股份", "change": -9.9},
            {"name": "某某科技", "change": -9.5}
        ]
    }


@pytest.fixture
def mock_db_session():
    """Mock database session"""
    session = MagicMock()
    session.query = MagicMock()
    session.add = MagicMock()
    session.commit = MagicMock()
    session.rollback = MagicMock()
    session.close = MagicMock()
    return session


@pytest.fixture
def mock_akshare_df():
    """Mock akshare DataFrame"""
    import pandas as pd
    data = {
        "代码": ["000001", "000002", "600000"],
        "名称": ["平安银行", "万科A", "浦发银行"],
        "最新价": [10.5, 15.2, 8.8],
        "涨跌幅": [5.0, -2.0, 1.5],
        "成交量": [1000000, 2000000, 1500000],
        "成交额": [10500000, 30400000, 13200000],
        "最高": [11.0, 15.5, 9.0],
        "最低": [10.0, 15.0, 8.5],
        "今开": [10.2, 15.3, 8.7],
        "昨收": [10.0, 15.5, 8.7],
        "市盈率-动态": [8.5, 12.0, 6.5],
        "市净率": [1.2, 1.5, 0.8],
        "总市值": [2000000000, 3000000000, 1500000000]
    }
    return pd.DataFrame(data)


@pytest.fixture
def mock_vllm_response():
    """Mock vLLM API response"""
    return {
        "id": "chatcmpl-test123",
        "object": "chat.completion",
        "created": int(datetime.now().timestamp()),
        "model": "Fin-R1-Live",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": "这是一个测试响应"
                },
                "finish_reason": "stop"
            }
        ],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "total_tokens": 150
        }
    }


@pytest.fixture(scope="function")
def cleanup_cache():
    """Cleanup cache after each test"""
    yield
    # Clear any module-level caches
    try:
        from realtime_fetcher import fetcher
        if hasattr(fetcher, '_cache'):
            fetcher._cache.clear()
        if hasattr(fetcher, '_market_cache'):
            fetcher._market_cache = None
    except ImportError:
        pass


@pytest.fixture
def test_client():
    """Create FastAPI test client"""
    from fastapi.testclient import TestClient
    
    # Import and create app with mocked dependencies
    with patch.dict(os.environ, {'DATABASE_URL': 'postgresql://test:test@localhost:5432/test_db'}):
        from main import app
        client = TestClient(app)
        yield client


# Database fixtures
@pytest.fixture
def mock_engine():
    """Mock SQLAlchemy engine"""
    with patch('database.create_engine') as mock:
        mock_engine = MagicMock()
        mock.return_value = mock_engine
        yield mock_engine


@pytest.fixture
def mock_session_factory():
    """Mock session factory"""
    with patch('database.SessionLocal') as mock:
        session = MagicMock()
        mock.return_value = session
        yield session


# API mocking fixtures
@pytest.fixture
def mock_httpx_client():
    """Mock httpx AsyncClient"""
    with patch('main.http_client') as mock:
        mock_client = AsyncMock()
        mock.return_value = mock_client
        yield mock_client


@pytest.fixture
def mock_akshare():
    """Mock akshare functions"""
    with patch('realtime_fetcher.ak') as mock_ak, \
         patch('history_downloader.ak') as mock_ak2, \
         patch('auto_sync.ak') as mock_ak3:
        
        # Setup mock returns
        import pandas as pd
        mock_df = pd.DataFrame({
            "代码": ["000001"],
            "名称": ["测试股票"],
            "最新价": [10.0],
            "涨跌幅": [1.0]
        })
        
        mock_ak.stock_zh_a_spot_em.return_value = mock_df
        mock_ak.stock_info_a_code_name.return_value = mock_df
        mock_ak.stock_zh_a_hist.return_value = mock_df
        
        mock_ak2.stock_info_a_code_name.return_value = mock_df
        mock_ak2.stock_zh_a_hist.return_value = mock_df
        
        mock_ak3.stock_info_a_code_name.return_value = mock_df
        mock_ak3.stock_zh_a_hist.return_value = mock_df
        
        yield mock_ak


# Async fixtures
@pytest.fixture
def async_mock():
    """Helper to create async mocks"""
    def create_async_mock(return_value=None):
        mock = AsyncMock()
        mock.return_value = return_value
        return mock
    return create_async_mock


@pytest.fixture
def mock_async_context_manager():
    """Helper for async context managers"""
    class MockAsyncContextManager:
        def __init__(self, return_value=None):
            self.return_value = return_value
        
        async def __aenter__(self):
            return self.return_value
        
        async def __aexit__(self, exc_type, exc, tb):
            pass
    
    return MockAsyncContextManager


# Configuration fixtures
@pytest.fixture
def test_settings():
    """Test settings"""
    from config import Settings
    return Settings(
        HOST="127.0.0.1",
        PORT=9999,
        VLLM_BASE_URL="http://test:8010",
        DATABASE_URL="postgresql://test:test@localhost:5432/test_db",
        LOG_LEVEL="DEBUG"
    )
