"""Configuration E2E — Settings 在真实环境下的加载."""

import pytest

from src.common.config import settings, Settings

pytestmark = pytest.mark.timeout(10)


class TestSettingsLoading:
    def test_settings_singleton(self):
        assert isinstance(settings, Settings)

    def test_database_url_present(self):
        assert settings.database.url
        assert "postgresql" in settings.database.url

    def test_selection_config(self):
        assert settings.selection.ma_filter.compute_periods
        assert settings.selection.output_dir


class TestSchedulerConfig:
    def test_scheduler_times_are_strings(self):
        assert isinstance(settings.scheduler.daily_sync_time, str)

    def test_scheduler_numeric_params(self):
        assert settings.scheduler.sync_days_back >= 1


class TestDatabaseConnectivity:
    def test_database_url_connects(self, pg_engine):
        from sqlalchemy import text
        with pg_engine.connect() as conn:
            result = conn.execute(text("SELECT current_database()")).scalar()
            assert result is not None
