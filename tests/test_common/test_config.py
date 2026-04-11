"""Tests for src/common/config.py"""
from src.common.config import (
    DatabaseConfig,
    QMTConfig,
    DownloadConfig,
    MLConfig,
    MLIterateConfig,
    BacktestConfig,
    RiskConfig,
    TradingConfig,
    APIConfig,
    WebhookConfig,
    Settings,
)


class TestDatabaseConfig:
    def test_defaults(self):
        cfg = DatabaseConfig()
        assert isinstance(cfg.url, str)
        assert cfg.pool_size >= 1
        assert cfg.max_overflow >= 0
        assert cfg.pool_timeout >= 1
        assert cfg.pool_recycle >= 0

    def test_no_hardcoded_credentials(self):
        """Verify no plaintext passwords in code defaults."""
        cfg = DatabaseConfig(_env_file=None)
        assert "1234" not in cfg.url
        assert "asdf" not in cfg.url

    def test_custom_values(self):
        cfg = DatabaseConfig(url="postgresql://localhost:5432/test_db", pool_size=3, max_overflow=6)
        assert cfg.url == "postgresql://localhost:5432/test_db"
        assert cfg.pool_size == 3
        assert cfg.max_overflow == 6


class TestQMTConfig:
    def test_defaults(self):
        cfg = QMTConfig(_env_file=None)
        assert cfg.qmt_path == ""
        assert cfg.account_id == ""
        assert cfg.account_type == "STOCK"


class TestDownloadConfig:
    def test_defaults(self):
        cfg = DownloadConfig(_env_file=None)
        assert cfg.batch_size == 500
        assert cfg.batch_pause == 2.0
        assert cfg.retry_count == 3
        assert cfg.retry_delay == 5.0
        assert cfg.download_timeout == 600
        assert cfg.default_start_1d == "20160101"
        assert cfg.default_start_1m == "20250101"
        assert cfg.default_start_5m == "20230101"


class TestMLIterateConfig:
    def test_defaults(self):
        cfg = MLIterateConfig(_env_file=None)
        assert cfg.max_iterations == 50
        assert cfg.target_sharpe == 2.0
        assert cfg.convergence_patience == 10
        assert cfg.initial_top_n == 30
        assert cfg.min_factors == 5


class TestMLConfig:
    def test_defaults(self):
        cfg = MLConfig(_env_file=None)
        assert cfg.model_dir == "./models"
        assert cfg.label_period == 2
        assert cfg.train_window == 252
        assert cfg.retrain_step == 21
        assert isinstance(cfg.iterate, MLIterateConfig)


class TestBacktestConfig:
    def test_defaults(self):
        cfg = BacktestConfig(_env_file=None)
        assert cfg.initial_capital == 1_000_000.0
        assert cfg.max_position_pct == 0.20
        assert cfg.max_total_position_pct == 0.80
        assert cfg.max_holdings == 5


class TestRiskConfig:
    def test_defaults(self):
        cfg = RiskConfig(_env_file=None)
        assert cfg.stop_loss_pct == -8.0
        assert cfg.take_profit_pct == 20.0
        assert cfg.max_single_position_pct == 30.0
        assert cfg.max_total_position_pct == 80.0
        assert cfg.max_daily_loss_pct == -5.0


class TestTradingConfig:
    def test_defaults(self):
        cfg = TradingConfig(_env_file=None)
        assert cfg.paper_trading is True
        assert isinstance(cfg.risk, RiskConfig)


class TestAPIConfig:
    def test_defaults(self):
        cfg = APIConfig(_env_file=None)
        assert cfg.host == "0.0.0.0"
        assert cfg.port == 8012


class TestWebhookConfig:
    def test_defaults(self):
        cfg = WebhookConfig(_env_file=None)
        assert cfg.openclaw_url == ""
        assert cfg.feishu_url == ""
        assert cfg.feishu_app_id == ""
        assert cfg.feishu_app_secret == ""


class TestSettings:
    def test_defaults(self):
        s = Settings(_env_file=None)
        assert s.log_level == "INFO"
        assert isinstance(s.database, DatabaseConfig)
        assert isinstance(s.qmt, QMTConfig)
        assert isinstance(s.download, DownloadConfig)
        assert isinstance(s.ml, MLConfig)
        assert isinstance(s.backtest, BacktestConfig)
        assert isinstance(s.trading, TradingConfig)
        assert isinstance(s.api, APIConfig)
        assert isinstance(s.webhook, WebhookConfig)

    def test_env_file_path_points_to_root(self):
        assert ".env" in str(Settings.model_config.get("env_file", ""))
