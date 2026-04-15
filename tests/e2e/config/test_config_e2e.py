"""Configuration E2E — 验证 Settings 在真实环境下的加载与一致性

测试范围:
  - Settings 核心字段加载
  - 数据库连接参数与真实 PG 一致
  - API Key 配置 (默认 disabled)
  - Scheduler / Webhook / 各策略子配置加载
  - 类型安全校验 (list 字段不再是 JSON 字符串)
"""
import pytest

from src.common.config import settings, Settings


pytestmark = pytest.mark.timeout(10)


class TestSettingsLoading:
    """Settings 实例化与核心字段"""

    def test_settings_singleton(self):
        assert isinstance(settings, Settings)

    def test_database_url_present(self):
        assert settings.database.url
        assert "postgresql" in settings.database.url

    def test_database_pool_params_positive(self):
        assert settings.database.pool_size > 0
        assert settings.database.max_overflow >= 0
        assert settings.database.pool_timeout > 0
        assert settings.database.pool_recycle > 0

    def test_database_init_retry_params(self):
        assert settings.database.init_max_retries >= 1
        assert settings.database.init_backoff_base >= 1


class TestAPIConfig:
    """API 子配置"""

    def test_api_key_disabled_by_default(self):
        assert settings.api.api_key_enabled is False

    def test_cors_origins_is_string(self):
        assert isinstance(settings.api.cors_origins, str)

    def test_api_host_and_port(self):
        assert isinstance(settings.api.host, str)
        assert isinstance(settings.api.port, int)


class TestSchedulerConfig:
    """Scheduler 子配置"""

    def test_scheduler_times_are_strings(self):
        assert isinstance(settings.scheduler.daily_sync_time, str)
        assert isinstance(settings.scheduler.snapshot_time, str)

    def test_scheduler_numeric_params(self):
        assert settings.scheduler.sync_days_back >= 1
        assert settings.scheduler.retrain_weeks >= 1
        assert settings.scheduler.poll_interval_sec >= 1


class TestWebhookConfig:
    """Webhook 子配置"""

    def test_webhook_http_params(self):
        assert settings.webhook.http_read_timeout > 0
        assert settings.webhook.max_connections >= 1


class TestDatabaseConnectivity:
    """配置的数据库 URL 能实际连接"""

    def test_database_url_connects(self, pg_engine):
        from sqlalchemy import text
        with pg_engine.connect() as conn:
            result = conn.execute(text("SELECT current_database()")).scalar()
            assert result is not None


class TestTypeSafeConfig:
    """P13: JSON 字符串已转为原生 list 类型"""

    def test_etf_rotation_canary_pool_is_list(self):
        pool = settings.etf_rotation.canary_pool
        assert isinstance(pool, list)

    def test_etf_rotation_defensive_pool_is_list(self):
        pool = settings.etf_rotation.defensive_pool
        assert isinstance(pool, list)

    def test_factor_pipeline_alpha158_windows_is_list(self):
        windows = settings.factor_pipeline.alpha158_windows
        assert isinstance(windows, list)
        if windows:
            assert all(isinstance(w, int) for w in windows)

    def test_portfolio_caa_cash_assets_is_list(self):
        assets = settings.portfolio.caa_cash_assets
        assert isinstance(assets, list)


class TestResilienceConfig:
    """韧性配置"""

    def test_resilience_params(self):
        assert settings.resilience.circuit_breaker_threshold >= 1
        assert settings.resilience.recovery_timeout_sec > 0


class TestStrategyConfigs:
    """策略子配置完整性抽查"""

    def test_backtest_config(self):
        assert settings.backtest.initial_capital > 0
        assert settings.backtest.commission_rate > 0

    def test_trading_rules_config(self):
        prefixes = settings.trading_rules.cross_border_etf_prefixes
        assert isinstance(prefixes, list)

    def test_signal_defaults_config(self):
        assert isinstance(settings.signal_defaults.stop_loss_pct, (int, float))
