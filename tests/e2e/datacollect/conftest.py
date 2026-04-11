"""数据采集 E2E 测试 fixtures

使用独立的 PostgreSQL schema (datacollect_e2e) 隔离,
session 级创建/销毁, 每个 test function 通过 SAVEPOINT 回滚。

运行方式:
  pytest tests/e2e/datacollect/ -v --timeout=120
"""
import pytest

from sqlalchemy import create_engine, text, event, MetaData
from sqlalchemy.orm import sessionmaker

from src.common.config import settings
from src.common.db import Base
import src.data.models  # noqa: F401 — 注册 ORM 模型
import src.datacollect.models  # noqa: F401 — 注册 CollectLog 模型

DC_SCHEMA = "datacollect_e2e"


@pytest.fixture(scope="session")
def dc_engine():
    """创建隔离的 datacollect_e2e schema 并建表"""
    engine = create_engine(
        settings.database.url,
        pool_size=3,
        max_overflow=5,
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute(f"SET search_path TO {DC_SCHEMA}, public")
        cursor.close()

    with engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {DC_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {DC_SCHEMA}"))
        conn.commit()

    dc_meta = MetaData(schema=DC_SCHEMA)
    for table in Base.metadata.sorted_tables:
        table.to_metadata(dc_meta, schema=DC_SCHEMA)
    dc_meta.create_all(bind=engine)

    yield engine

    with engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {DC_SCHEMA} CASCADE"))
        conn.commit()
    engine.dispose()


@pytest.fixture(scope="session")
def dc_session_factory(dc_engine):
    return sessionmaker(bind=dc_engine)


@pytest.fixture
def dc_session(dc_session_factory):
    """每个测试用例的 DB session, 测试后 rollback"""
    session = dc_session_factory()
    session.execute(text(f"SET search_path TO {DC_SCHEMA}, public"))
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def dc_get_session(dc_session_factory):
    """替换 src.common.db.get_session 用的 context manager 工厂"""
    from contextlib import contextmanager

    @contextmanager
    def _override():
        session = dc_session_factory()
        session.execute(text(f"SET search_path TO {DC_SCHEMA}, public"))
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _override
