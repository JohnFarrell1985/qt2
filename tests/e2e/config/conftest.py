"""Config E2E — conftest

验证配置系统在真实环境下的加载与验证行为。
"""
import pytest
from sqlalchemy import create_engine, text

from src.common.config import settings


@pytest.fixture(scope="session")
def pg_engine():
    engine = create_engine(
        settings.database.url,
        pool_size=2,
        max_overflow=3,
        pool_pre_ping=True,
    )
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield engine
    engine.dispose()
