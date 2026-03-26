"""
Tests for config.py - Settings validation
"""
import pytest
from pydantic import ValidationError


class TestSettings:
    """Test suite for Settings configuration"""
    
    def test_default_settings(self, test_settings):
        """Test default configuration values"""
        assert test_settings.HOST == "127.0.0.1"
        assert test_settings.PORT == 9999
        assert test_settings.VLLM_MODEL == "/models/Fin-R1"
        assert test_settings.LOG_LEVEL == "DEBUG"
    
    def test_port_validation_valid(self):
        """Test port validation with valid values"""
        from config import Settings
        
        # Valid port - minimum
        s1 = Settings(PORT=1)
        assert s1.PORT == 1
        
        # Valid port - maximum
        s2 = Settings(PORT=65535)
        assert s2.PORT == 65535
        
        # Valid port - typical
        s3 = Settings(PORT=8012)
        assert s3.PORT == 8012
    
    def test_port_validation_invalid(self):
        """Test port validation with invalid values"""
        from config import Settings
        
        # Port too low
        with pytest.raises(ValidationError) as exc_info:
            Settings(PORT=0)
        assert "PORT" in str(exc_info.value)
        
        # Port too high
        with pytest.raises(ValidationError) as exc_info:
            Settings(PORT=65536)
        assert "PORT" in str(exc_info.value)
        
        # Negative port
        with pytest.raises(ValidationError) as exc_info:
            Settings(PORT=-1)
        assert "PORT" in str(exc_info.value)
    
    def test_workers_validation(self):
        """Test workers validation"""
        from config import Settings
        
        # Valid workers
        s1 = Settings(WORKERS=1)
        assert s1.WORKERS == 1
        
        s2 = Settings(WORKERS=8)
        assert s2.WORKERS == 8
        
        # Invalid workers - too high
        with pytest.raises(ValidationError) as exc_info:
            Settings(WORKERS=9)
        assert "WORKERS" in str(exc_info.value)
        
        # Invalid workers - zero
        with pytest.raises(ValidationError) as exc_info:
            Settings(WORKERS=0)
        assert "WORKERS" in str(exc_info.value)
    
    def test_vllm_timeout_validation(self):
        """Test vLLM timeout validation"""
        from config import Settings
        
        # Valid timeout
        s1 = Settings(VLLM_TIMEOUT=10)
        assert s1.VLLM_TIMEOUT == 10
        
        s2 = Settings(VLLM_TIMEOUT=300)
        assert s2.VLLM_TIMEOUT == 300
        
        # Invalid - too short
        with pytest.raises(ValidationError) as exc_info:
            Settings(VLLM_TIMEOUT=5)
        assert "VLLM_TIMEOUT" in str(exc_info.value)
        
        # Invalid - too long
        with pytest.raises(ValidationError) as exc_info:
            Settings(VLLM_TIMEOUT=301)
        assert "VLLM_TIMEOUT" in str(exc_info.value)
    
    def test_log_level_validation(self):
        """Test log level validation"""
        from config import Settings
        
        # Valid log levels
        for level in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            s = Settings(LOG_LEVEL=level)
            assert s.LOG_LEVEL == level
        
        # Invalid log level
        with pytest.raises(ValidationError) as exc_info:
            Settings(LOG_LEVEL="INVALID")
        assert "LOG_LEVEL" in str(exc_info.value)
    
    def test_max_data_stocks_validation(self):
        """Test max data stocks validation"""
        from config import Settings
        
        # Valid values
        s1 = Settings(MAX_DATA_STOCKS=1)
        assert s1.MAX_DATA_STOCKS == 1
        
        s2 = Settings(MAX_DATA_STOCKS=50)
        assert s2.MAX_DATA_STOCKS == 50
        
        # Invalid - too high
        with pytest.raises(ValidationError) as exc_info:
            Settings(MAX_DATA_STOCKS=51)
        assert "MAX_DATA_STOCKS" in str(exc_info.value)
    
    def test_cors_origins_parsing(self):
        """Test CORS origins parsing"""
        from config import Settings
        
        # Single origin
        s1 = Settings(CORS_ORIGINS="http://localhost:8011")
        assert s1.CORS_ORIGINS == ["http://localhost:8011"]
        
        # Multiple origins
        s2 = Settings(CORS_ORIGINS="http://localhost:8011,https://example.com")
        assert s2.CORS_ORIGINS == ["http://localhost:8011", "https://example.com"]
        
        # Wildcard
        s3 = Settings(CORS_ORIGINS="*")
        assert s3.CORS_ORIGINS == ["*"]
    
    def test_database_url(self, test_settings):
        """Test database URL configuration"""
        assert "postgresql://" in test_settings.DATABASE_URL
        assert "test" in test_settings.DATABASE_URL
    
    def test_environment_override(self, monkeypatch):
        """Test environment variable override"""
        from config import Settings
        
        # Set environment variable
        monkeypatch.setenv("PORT", "9000")
        monkeypatch.setenv("LOG_LEVEL", "ERROR")
        
        # Create new settings (should read from env)
        s = Settings()
        assert s.PORT == 9000
        assert s.LOG_LEVEL == "ERROR"
    
    def test_boolean_fields(self):
        """Test boolean configuration fields"""
        from config import Settings
        
        s1 = Settings(ENABLE_REALTIME_API=True, ENABLE_DB_HISTORY=False)
        assert s1.ENABLE_REALTIME_API is True
        assert s1.ENABLE_DB_HISTORY is False
        
        s2 = Settings(ENABLE_REALTIME_API=False, ENABLE_DB_HISTORY=True)
        assert s2.ENABLE_REALTIME_API is False
        assert s2.ENABLE_DB_HISTORY is True
    
    def test_cache_ttl_validation(self):
        """Test cache TTL validation"""
        from config import Settings
        
        # Valid TTL
        s1 = Settings(DATA_CACHE_TTL=10)
        assert s1.DATA_CACHE_TTL == 10
        
        s2 = Settings(DATA_CACHE_TTL=300)
        assert s2.DATA_CACHE_TTL == 300
        
        # Invalid - too short
        with pytest.raises(ValidationError) as exc_info:
            Settings(DATA_CACHE_TTL=5)
        assert "DATA_CACHE_TTL" in str(exc_info.value)
