"""
Tests for database_client.py
"""
import pytest
from datetime import date, timedelta
from unittest.mock import Mock, patch, MagicMock, call
from sqlalchemy import text


class TestGetDBSession:
    """Test get_db_session context manager"""
    
    def test_session_creation(self, mock_session_factory):
        """Test session is created and closed properly"""
        from database_client import get_db_session
        
        with patch('database_client.SessionLocal', return_value=mock_session_factory):
            with get_db_session() as session:
                assert session == mock_session_factory
            
            # Should close on exit
            mock_session_factory.close.assert_called_once()
    
    def test_session_commit(self, mock_session_factory):
        """Test session commits on success"""
        from database_client import get_db_session
        
        with patch('database_client.SessionLocal', return_value=mock_session_factory):
            with get_db_session() as session:
                pass  # No exception
            
            mock_session_factory.commit.assert_called_once()
    
    def test_session_rollback_on_error(self, mock_session_factory):
        """Test session rolls back on exception"""
        from database_client import get_db_session
        
        with patch('database_client.SessionLocal', return_value=mock_session_factory):
            with pytest.raises(ValueError):
                with get_db_session() as session:
                    raise ValueError("Test error")
            
            mock_session_factory.rollback.assert_called_once()
            mock_session_factory.close.assert_called_once()


class TestHistoryDataClient:
    """Test HistoryDataClient class"""
    
    @pytest.fixture
    def mock_session(self):
        """Create mock session with execute method"""
        session = MagicMock()
        session.execute = MagicMock()
        return session
    
    def test_get_stock_history_success(self, mock_session):
        """Test getting stock history successfully"""
        from database_client import HistoryDataClient
        
        # Mock database result
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
        
        mock_session.execute.return_value = [mock_row]
        
        with patch('database_client.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            history = HistoryDataClient.get_stock_history("000001", 30)
            
            assert len(history) == 1
            assert history[0]["code"] == "000001"
            assert history[0]["close"] == 10.2
    
    def test_get_stock_history_empty(self, mock_session):
        """Test getting stock history with no data"""
        from database_client import HistoryDataClient
        
        mock_session.execute.return_value = []
        
        with patch('database_client.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            history = HistoryDataClient.get_stock_history("000001", 30)
            
            assert len(history) == 0
    
    def test_get_stock_history_error(self):
        """Test handling database error"""
        from database_client import HistoryDataClient
        
        with patch('database_client.get_db_session', side_effect=Exception("DB Error")):
            history = HistoryDataClient.get_stock_history("000001", 30)
            
            assert len(history) == 0
    
    def test_get_stock_statistics_success(self, mock_session):
        """Test getting stock statistics"""
        from database_client import HistoryDataClient
        
        # Mock first() call for current_price subquery
        mock_price_row = MagicMock()
        mock_price_row.close = 10.5
        
        # Mock statistics query result
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
        
        # Setup mock to return different results for different queries
        mock_session.execute.side_effect = [
            [MagicMock(trade_date=date(2024, 1, 15))],  # latest date
            [mock_price_row],  # current price
            [mock_stats_row]   # statistics
        ]
        
        with patch('database_client.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            stats = HistoryDataClient.get_stock_statistics("000001", 30)
            
            assert stats["code"] == "000001"
            assert stats["current_price"] == 10.5
            assert stats["period_high"] == 11.0
            assert stats["up_days"] == 15
    
    def test_get_stock_statistics_no_data(self, mock_session):
        """Test getting statistics with no data"""
        from database_client import HistoryDataClient
        
        mock_session.execute.return_value = []  # No latest date
        
        with patch('database_client.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            stats = HistoryDataClient.get_stock_statistics("000001", 30)
            
            assert stats == {}
    
    def test_search_stocks_success(self, mock_session):
        """Test searching stocks"""
        from database_client import HistoryDataClient
        
        mock_row = MagicMock()
        mock_row.code = "000001"
        mock_row.name = "平安银行"
        mock_row.exchange = "SZ"
        mock_row.industry = "银行"
        mock_row.pe_ttm = 8.5
        mock_row.pb = 1.2
        
        mock_session.execute.return_value = [mock_row]
        
        with patch('database_client.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            results = HistoryDataClient.search_stocks("平安", limit=10)
            
            assert len(results) == 1
            assert results[0]["code"] == "000001"
            assert results[0]["name"] == "平安银行"
    
    def test_search_stocks_no_results(self, mock_session):
        """Test searching with no results"""
        from database_client import HistoryDataClient
        
        mock_session.execute.return_value = []
        
        with patch('database_client.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            results = HistoryDataClient.search_stocks("不存在的股票")
            
            assert len(results) == 0
    
    def test_get_db_status_connected(self, mock_session):
        """Test getting database status - connected"""
        from database_client import HistoryDataClient
        
        # Mock count queries
        mock_session.query.return_value.count.side_effect = [5000, 1000000, 0]
        mock_session.execute.return_value.scalar.side_effect = [date(2024, 1, 15)]
        
        with patch('database_client.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            status = HistoryDataClient.get_db_status()
            
            assert status["connected"] is True
            assert "table_counts" in status
    
    def test_get_db_status_error(self):
        """Test getting database status - error"""
        from database_client import HistoryDataClient
        
        with patch('database_client.get_db_session', side_effect=Exception("Connection failed")):
            status = HistoryDataClient.get_db_status()
            
            assert status["connected"] is False
            assert "error" in status
    
    def test_sql_injection_protection(self, mock_session):
        """Test that SQL injection is prevented via parameterization"""
        from database_client import HistoryDataClient
        
        mock_session.execute.return_value = []
        
        with patch('database_client.get_db_session') as mock_get_session:
            mock_get_session.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_get_session.return_value.__exit__ = MagicMock(return_value=False)
            
            # Try SQL injection - should be handled safely via parameterization
            HistoryDataClient.get_stock_statistics("000001'; DROP TABLE stocks; --", 30)
            
            # Get the actual SQL executed
            calls = mock_session.execute.call_args_list
            for call in calls:
                args, kwargs = call
                sql = str(args[0]) if args else ""
                
                # The parameter should be escaped/parameterized
                if "DROP TABLE" in str(sql):
                    pytest.fail("SQL injection not properly prevented!")
