"""Database E2E — conftest

独立 schema 隔离, 测试 BulkWriter / get_session / 数据库连接等核心组件。
写入测试使用 db_e2e_test schema, 测试后清理。
"""
import pytest
from contextlib import contextmanager

from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import sessionmaker

from src.common.config import settings
from src.common.db import Base
import src.data.models  # noqa: F401
import src.datacollect.models  # noqa: F401
import src.sentiment.models  # noqa: F401

DB_E2E_SCHEMA = "db_e2e_test"


@pytest.fixture(scope="session")
def pg_engine():
    engine = create_engine(
        settings.database.url,
        pool_size=3,
        max_overflow=5,
        pool_pre_ping=True,
    )
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def db_e2e_engine():
    """写入测试专用引擎 — 独立 schema 隔离"""
    engine = create_engine(
        settings.database.url,
        pool_size=3,
        max_overflow=5,
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute(f"SET search_path TO {DB_E2E_SCHEMA}, public")
        cursor.close()

    with engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {DB_E2E_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {DB_E2E_SCHEMA}"))
        conn.commit()

    original_schemas = {}
    for table_name, table in Base.metadata.tables.items():
        original_schemas[table_name] = table.schema
        table.schema = DB_E2E_SCHEMA

    Base.metadata.create_all(bind=engine)

    yield engine

    with engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {DB_E2E_SCHEMA} CASCADE"))
        conn.commit()

    for table_name, table in Base.metadata.tables.items():
        table.schema = original_schemas.get(table_name)

    engine.dispose()


@pytest.fixture
def db_e2e_session(db_e2e_engine):
    """每个测试一个 session, 测试后 rollback"""
    factory = sessionmaker(bind=db_e2e_engine)
    session = factory()
    session.execute(text(f"SET search_path TO {DB_E2E_SCHEMA}, public"))
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def make_e2e_get_session(db_e2e_engine):
    """构造可替换 src.common.db.get_session 的上下文管理器工厂"""
    factory = sessionmaker(bind=db_e2e_engine)

    def _factory(readonly: bool = False):
        @contextmanager
        def _override():
            session = factory()
            session.execute(text(f"SET search_path TO {DB_E2E_SCHEMA}, public"))
            try:
                yield session
                if readonly:
                    session.rollback()
                else:
                    session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()
        return _override()

    return _factory
