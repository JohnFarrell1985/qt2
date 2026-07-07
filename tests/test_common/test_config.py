"""Tests for src/common/config.py"""

from src.common.config import (
    BacktestConfig,
    DatabaseConfig,
    DownloadConfig,
    MaFilterConfig,
    QMTConfig,
    SelectionConfig,
    Settings,
    TradingConfig,
)


class TestDatabaseConfig:
    def test_defaults(self):
        cfg = DatabaseConfig()
        assert isinstance(cfg.url, str)
        assert cfg.pool_size >= 1


class TestQMTConfig:
    def test_defaults(self):
        cfg = QMTConfig(_env_file=None)
        assert cfg.qmt_path == ""
        assert cfg.account_type == "STOCK"


class TestDownloadConfig:
    def test_defaults(self):
        cfg = DownloadConfig(_env_file=None)
        assert cfg.batch_size == 500
        assert cfg.default_start_1d == "20160101"


class TestSelectionConfig:
    def test_ma_filter_defaults(self):
        cfg = MaFilterConfig(_env_file=None)
        assert 5 in cfg.compute_periods
        assert cfg.require_bullish_order is True


class TestBacktestConfig:
    def test_defaults(self):
        cfg = BacktestConfig(_env_file=None)
        assert cfg.initial_capital == 1_000_000.0
        assert cfg.max_holdings == 5


class TestSettings:
    def test_aggregate(self):
        s = Settings(_env_file=None)
        assert isinstance(s.database, DatabaseConfig)
        assert isinstance(s.selection, SelectionConfig)
        assert isinstance(s.trading, TradingConfig)
