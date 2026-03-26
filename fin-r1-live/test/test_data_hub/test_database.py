"""
Tests for data-hub database.py
"""
import pytest
from datetime import datetime, date
from unittest.mock import Mock, patch, MagicMock
from sqlalchemy import text


class TestStockModel:
    """Test Stock ORM model"""
    
    def test_stock_to_dict(self):
        """Test Stock to_dict method"""
        from database import Stock
        
        stock = Stock(
            code="000001",
            name="平安银行",
            exchange="SZ",
            industry="银行",
            pe_ttm=8.5,
            pb=1.2,
            market_cap=2000.0
        )
        
        result = stock.to_dict()
        
        assert result["code"] == "000001"
        assert result["name"] == "平安银行"
        assert result["exchange"] == "SZ"
        assert result["pe_ttm"] == 8.5
    
    def test_stock_optional_fields(self):
        """Test Stock with optional fields as None"""
        from database import Stock
        
        stock = Stock(
            code="000002",
            name="万科A",
            exchange="SZ"
        )
        
        result = stock.to_dict()
        
        assert result["code"] == "000002"
        assert result["industry"] is None
        assert result["pe_ttm"] is None


class TestStockDailyModel:
    """Test StockDaily ORM model"""
    
    def test_stock_daily_to_dict(self):
        """Test StockDaily to_dict"""
        from database import StockDaily
        
        daily = StockDaily(
            code="000001",
            trade_date=date(2024, 1, 15),
            open=10.0,
            high=10.5,
            low=9.8,
            close=10.2,
            volume=500000,
            amount=5100000,
            change_pct=2.0,
            turnover_rate=0.5
        )
        
        result = daily.to_dict()
        
        assert result["code"] == "000001"
        assert result["close"] == 10.2
        assert result["trade_date"] == "2024-01-15"
    
    def test_stock_daily_optional_fields(self):
        """Test StockDaily with optional fields"""
        from database import StockDaily
        
        daily = StockDaily(
            code="000001",
            trade_date=date(2024, 1, 15),
            open=10.0,
            high=10.0,
            low=10.0,
            close=10.0
        )
        
        result = daily.to_dict()
        
        assert result["volume"] is None
        assert result["change_pct"] is None


class TestInitDatabase:
    """Test database initialization"""
    
    def test_init_database(self):
        """Test database initialization"""
        with patch('database.engine') as mock_engine:
            from database import init_database
            
            init_database()
            
            mock_engine.execute.assert_called()
    
    def test_init_database_error(self):
        """Test handling init error"""
        with patch('database.engine', side_effect=Exception("DB Error")):
            from database import init_database
            
            with pytest.raises(Exception):
                init_database()


class TestGetDBSession:
    """Test database session context manager"""
    
    def test_session_commit_on_success(self):
        """Test session commits on success"""
        from database import get_db_session
        
        mock_session = MagicMock()
        
        with patch('database.SessionLocal', return_value=mock_session):
            with get_db_session() as session:
                pass
            
            mock_session.commit.assert_called_once()
            mock_session.close.assert_called_once()
    
    def test_session_rollback_on_error(self):
        """Test session rollback on error"""
        from database import get_db_session
        
        mock_session = MagicMock()
        
        with patch('database.SessionLocal', return_value=mock_session):
            with pytest.raises(ValueError):
                with get_db_session():
                    raise ValueError("Test error")
            
            mock_session.rollback.assert_called_once()
            mock_session.close.assert_called_once()


class TestStockDAO:
    """Test StockDAO"""
    
    def test_bulk_upsert_stocks_insert(self):
        """Test bulk upsert - insert new stocks"""
        from database import StockDAO, Stock
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = None
        
        stocks_data = [
            {"code": "000001", "name": "平安银行", "exchange": "SZ"},
            {"code": "000002", "name": "万科A", "exchange": "SZ"}
        ]
        
        StockDAO.bulk_upsert_stocks(mock_session, stocks_data)
        
        assert mock_session.add.call_count == 2
    
    def test_bulk_upsert_stocks_update(self):
        """Test bulk upsert - update existing stocks"""
        from database import StockDAO, Stock
        
        existing_stock = Stock(code="000001", name="Old Name")
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = existing_stock
        
        stocks_data = [
            {"code": "000001", "name": "平安银行", "exchange": "SZ"}
        ]
        
        StockDAO.bulk_upsert_stocks(mock_session, stocks_data)
        
        # Should update existing stock
        assert existing_stock.name == "平安银行"
        assert existing_stock.exchange == "SZ"
    
    def test_get_stock_by_code(self):
        """Test getting stock by code"""
        from database import StockDAO, Stock
        
        mock_stock = Stock(code="000001", name="平安银行")
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.first.return_value = mock_stock
        
        result = StockDAO.get_stock_by_code(mock_session, "000001")
        
        assert result == mock_stock
    
    def test_search_stocks_by_name(self):
        """Test searching stocks by name"""
        from database import StockDAO, Stock
        
        mock_stocks = [Stock(code="000001", name="平安银行")]
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = mock_stocks
        
        results = StockDAO.search_stocks_by_name(mock_session, "平安", 10)
        
        assert len(results) == 1
    
    def test_get_all_stock_codes(self):
        """Test getting all stock codes"""
        from database import StockDAO
        
        mock_session = MagicMock()
        mock_session.query.return_value.all.return_value = [("000001",), ("000002",)]
        
        codes = StockDAO.get_all_stock_codes(mock_session)
        
        assert codes == ["000001", "000002"]


class TestStockDailyDAO:
    """Test StockDailyDAO"""
    
    def test_bulk_insert_daily_data(self):
        """Test bulk insert daily data"""
        from database import StockDailyDAO
        
        mock_session = MagicMock()
        
        data_list = [
            {"code": "000001", "trade_date": date(2024, 1, 15), "close": 10.2},
            {"code": "000001", "trade_date": date(2024, 1, 16), "close": 10.5}
        ]
        
        count = StockDailyDAO.bulk_insert_daily_data(mock_session, data_list)
        
        assert count == 2
        mock_session.execute.assert_called()
    
    def test_get_stock_history(self):
        """Test getting stock history"""
        from database import StockDailyDAO, StockDaily
        
        mock_data = [
            StockDaily(code="000001", trade_date=date(2024, 1, 15), open=10.0, high=10.5, low=9.8, close=10.2),
            StockDaily(code="000001", trade_date=date(2024, 1, 16), open=10.2, high=10.6, low=10.0, close=10.5)
        ]
        
        mock_session = MagicMock()
        mock_query = MagicMock()
        mock_query.filter_by.return_value = mock_query
        mock_query.filter.return_value = mock_query
        mock_query.order_by.return_value.limit.return_value.all.return_value = mock_data
        mock_session.query.return_value = mock_query
        
        results = StockDailyDAO.get_stock_history(mock_session, "000001", limit=30)
        
        assert len(results) == 2
        assert results[0].close == 10.5  # Most recent first
    
    def test_get_latest_trade_date(self):
        """Test getting latest trade date"""
        from database import StockDailyDAO
        
        latest_date = date(2024, 1, 15)
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = (latest_date,)
        
        result = StockDailyDAO.get_latest_trade_date(mock_session, "000001")
        
        assert result == latest_date
    
    def test_get_date_range_statistics(self):
        """Test getting date range statistics"""
        from database import StockDailyDAO, StockDaily
        
        mock_data = [
            StockDaily(code="000001", trade_date=date(2024, 1, 10), close=10.0, high=10.5, low=9.8, volume=100000, change_pct=1.0),
            StockDaily(code="000001", trade_date=date(2024, 1, 11), close=10.5, high=10.8, low=10.0, volume=120000, change_pct=2.0),
        ]
        
        mock_session = MagicMock()
        mock_session.query.return_value.filter_by.return_value.order_by.return_value.first.return_value = (date(2024, 1, 11),)
        mock_session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = mock_data
        
        stats = StockDailyDAO.get_date_range_statistics(mock_session, "000001", 30)
        
        assert stats["code"] == "000001"
        assert stats["days"] == 2
        assert stats["current_price"] == 10.5
        assert stats["up_days"] == 2
