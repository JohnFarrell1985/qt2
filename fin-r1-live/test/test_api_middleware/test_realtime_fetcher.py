"""
Tests for realtime_fetcher.py
"""
import pytest
import asyncio
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, MagicMock, AsyncMock


class TestStockQuote:
    """Test StockQuote dataclass"""
    
    def test_stock_quote_creation(self, mock_stock_quote):
        """Test StockQuote dataclass creation"""
        from realtime_fetcher import StockQuote
        
        quote = StockQuote(**mock_stock_quote)
        assert quote.code == "000001"
        assert quote.name == "平安银行"
        assert quote.price == 10.5
        assert quote.change == 0.5
        assert quote.pe == 8.5
        assert quote.pb == 1.2
    
    def test_stock_quote_optional_fields(self):
        """Test StockQuote with optional fields as None"""
        from realtime_fetcher import StockQuote
        
        quote = StockQuote(
            code="000001",
            name="Test",
            price=10.0,
            change=0.0,
            change_percent=0.0,
            volume=1000,
            turnover=10000,
            high=11.0,
            low=9.0,
            open=10.0,
            pre_close=10.0,
            pe=None,
            pb=None,
            market_cap=None
        )
        assert quote.pe is None
        assert quote.pb is None
        assert quote.market_cap is None


class TestLRUCache:
    """Test LRUCache implementation"""
    
    def test_lru_cache_basic_operations(self):
        """Test basic cache get/set operations"""
        from realtime_fetcher import LRUCache
        
        cache = LRUCache(maxsize=3)
        
        # Set and get
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"
        
        # Get non-existent key
        assert cache.get("nonexistent") is None
    
    def test_lru_cache_eviction(self):
        """Test LRU eviction policy"""
        from realtime_fetcher import LRUCache
        
        cache = LRUCache(maxsize=3)
        
        # Fill cache
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        
        # Access key1 to make it recently used
        cache.get("key1")
        
        # Add new key, should evict key2 (least recently used)
        cache.set("key4", "value4")
        
        assert cache.get("key1") == "value1"  # Still there
        assert cache.get("key2") is None  # Evicted
        assert cache.get("key3") == "value3"  # Still there
        assert cache.get("key4") == "value4"  # New entry
    
    def test_lru_cache_update_existing(self):
        """Test updating existing key"""
        from realtime_fetcher import LRUCache
        
        cache = LRUCache(maxsize=3)
        
        cache.set("key1", "value1")
        cache.set("key1", "updated")
        
        assert cache.get("key1") == "updated"
        assert len(cache.cache) == 1
    
    def test_lru_cache_clear(self):
        """Test cache clear"""
        from realtime_fetcher import LRUCache
        
        cache = LRUCache(maxsize=3)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        cache.clear()
        
        assert cache.get("key1") is None
        assert cache.get("key2") is None
        assert len(cache.cache) == 0
        assert len(cache.access_order) == 0


class TestRealtimeDataFetcher:
    """Test RealtimeDataFetcher class"""
    
    @pytest.fixture
    def fetcher(self):
        """Create fetcher instance"""
        from realtime_fetcher import RealtimeDataFetcher
        return RealtimeDataFetcher(cache_ttl=60)
    
    @pytest.mark.asyncio
    async def test_get_quote_from_cache(self, fetcher, mock_akshare_df):
        """Test getting quote from cache"""
        # Pre-populate cache
        from realtime_fetcher import StockQuote
        cached_quote = StockQuote(
            code="000001",
            name="Cached",
            price=10.0,
            change=0.0,
            change_percent=0.0,
            volume=1000,
            turnover=10000,
            high=11.0,
            low=9.0,
            open=10.0,
            pre_close=10.0
        )
        fetcher._set_cache("quote_000001", cached_quote)
        
        # Should return from cache without calling API
        quote = await fetcher.get_quote("000001")
        assert quote == cached_quote
    
    @pytest.mark.asyncio
    async def test_get_quote_from_api(self, fetcher, mock_akshare_df):
        """Test getting quote from API"""
        with patch('realtime_fetcher.ak.stock_zh_a_spot_em', return_value=mock_akshare_df):
            quote = await fetcher.get_quote("000001")
            
            assert quote is not None
            assert quote.code == "000001"
            assert quote.name == "平安银行"
            assert quote.price == 10.5
            assert quote.change == 5.0
    
    @pytest.mark.asyncio
    async def test_get_quote_not_found(self, fetcher, mock_akshare_df):
        """Test getting quote for non-existent stock"""
        with patch('realtime_fetcher.ak.stock_zh_a_spot_em', return_value=mock_akshare_df):
            quote = await fetcher.get_quote("999999")  # Non-existent code
            assert quote is None
    
    @pytest.mark.asyncio
    async def test_get_quote_api_error(self, fetcher):
        """Test handling API error"""
        with patch('realtime_fetcher.ak.stock_zh_a_spot_em', side_effect=Exception("API Error")):
            quote = await fetcher.get_quote("000001")
            assert quote is None
    
    @pytest.mark.asyncio
    async def test_get_market_overview(self, fetcher, mock_akshare_df):
        """Test getting market overview"""
        with patch('realtime_fetcher.ak.stock_zh_a_spot_em', return_value=mock_akshare_df):
            overview = await fetcher.get_market_overview()
            
            assert "statistics" in overview
            assert "up" in overview["statistics"]
            assert "down" in overview["statistics"]
            assert "top_gainers" in overview
            assert "top_losers" in overview
    
    @pytest.mark.asyncio
    async def test_get_market_overview_cached(self, fetcher, mock_akshare_df):
        """Test market overview caching"""
        cached_data = {"cached": True}
        fetcher._set_cache("market_overview", cached_data)
        
        overview = await fetcher.get_market_overview()
        assert overview == cached_data
    
    @pytest.mark.asyncio
    async def test_search_stock(self, fetcher, mock_akshare_df):
        """Test searching stocks"""
        with patch('realtime_fetcher.ak.stock_zh_a_spot_em', return_value=mock_akshare_df):
            results = await fetcher.search_stock("平安")
            
            assert len(results) > 0
            assert results[0]["code"] == "000001"
            assert "平安" in results[0]["name"]
    
    @pytest.mark.asyncio
    async def test_search_stock_no_match(self, fetcher, mock_akshare_df):
        """Test searching with no matches"""
        with patch('realtime_fetcher.ak.stock_zh_a_spot_em', return_value=mock_akshare_df):
            results = await fetcher.search_stock("不存在的股票")
            assert len(results) == 0
    
    @pytest.mark.asyncio
    async def test_get_batch_quotes(self, fetcher, mock_akshare_df):
        """Test batch quote fetching"""
        with patch('realtime_fetcher.ak.stock_zh_a_spot_em', return_value=mock_akshare_df):
            quotes = await fetcher.get_batch_quotes(["000001", "000002"])
            
            assert len(quotes) == 2
            codes = [q.code for q in quotes]
            assert "000001" in codes
            assert "000002" in codes
    
    def test_format_for_llm_quote(self, fetcher):
        """Test formatting quote for LLM"""
        from realtime_fetcher import StockQuote
        
        quote = StockQuote(
            code="000001",
            name="平安银行",
            price=10.5,
            change=5.0,
            change_percent=5.0,
            volume=1000000,
            turnover=10500000,
            high=11.0,
            low=9.0,
            open=10.0,
            pre_close=10.0,
            pe=8.5,
            pb=1.2
        )
        
        formatted = fetcher.format_for_llm([quote], "quote")
        
        assert "平安银行" in formatted
        assert "000001" in formatted
        assert "10.5" in formatted
        assert "+5.0%" in formatted
    
    def test_format_for_llm_market(self, fetcher, mock_market_overview):
        """Test formatting market overview for LLM"""
        formatted = fetcher.format_for_lll(mock_market_overview, "market")
        
        assert "市场概览" in formatted
        assert "2500" in formatted  # up count
        assert "2000" in formatted  # down count
    
    @pytest.mark.asyncio
    async def test_market_data_cache(self, fetcher, mock_akshare_df):
        """Test market data caching with TTL"""
        with patch('realtime_fetcher.ak.stock_zh_a_spot_em', return_value=mock_akshare_df):
            # First call - should hit API
            df1 = await fetcher._get_market_data()
            
            # Second call - should use cache
            df2 = await fetcher._get_market_data()
            
            # Should be same object (from cache)
            assert df1 is df2
    
    @pytest.mark.asyncio
    async def test_market_data_cache_expiry(self, fetcher, mock_akshare_df):
        """Test market data cache expiry"""
        with patch('realtime_fetcher.ak.stock_zh_a_spot_em', return_value=mock_akshare_df):
            # Get data
            df1 = await fetcher._get_market_data()
            
            # Manually expire cache
            fetcher._market_cache_time = datetime.now() - timedelta(seconds=fetcher._market_cache_ttl + 1)
            
            # Next call should fetch new data
            with patch('realtime_fetcher.ak.stock_zh_a_spot_em', return_value=mock_akshare_df) as mock_api:
                df2 = await fetcher._get_market_data()
                mock_api.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_run_sync_timeout(self, fetcher):
        """Test async run with timeout"""
        async def slow_func():
            await asyncio.sleep(0.1)
            return "result"
        
        # Should complete within timeout
        result = await fetcher._run_sync(lambda: "result", timeout=5)
        assert result == "result"
    
    @pytest.mark.asyncio
    async def test_run_sync_timeout_error(self, fetcher):
        """Test async run timeout error"""
        def slow_func():
            import time
            time.sleep(10)  # This will be cancelled
            return "result"
        
        # Should timeout
        with pytest.raises(asyncio.TimeoutError):
            await fetcher._run_sync(slow_func, timeout=0.01)
