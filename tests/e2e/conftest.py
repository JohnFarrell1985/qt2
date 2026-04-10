"""E2E 测试核心 fixtures

PostgreSQL e2e_test schema 隔离. 每个 API 调用获得独立 session.
"""
import pytest
from contextlib import contextmanager

from sqlalchemy import create_engine, text, event
from sqlalchemy.orm import Session, sessionmaker
from unittest.mock import patch, MagicMock

from src.common.config import settings
from src.common.db import Base

from tests.e2e.fixtures.seed_market_data import (
    create_stocks, create_trading_dates, create_stock_daily,
)
from tests.e2e.fixtures.seed_factor_data import create_factor_meta, create_factor_values

E2E_SCHEMA = "e2e_test"


@pytest.fixture(scope="session")
def db_engine():
    """连接现有 PostgreSQL, 创建隔离的 e2e_test schema"""
    engine = create_engine(
        settings.database.url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )

    with engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {E2E_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {E2E_SCHEMA}"))
        conn.commit()

    original_schemas = {}
    for table_name, table in Base.metadata.tables.items():
        original_schemas[table_name] = table.schema
        table.schema = E2E_SCHEMA

    Base.metadata.create_all(bind=engine)

    yield engine

    with engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {E2E_SCHEMA} CASCADE"))
        conn.commit()

    for table_name, table in Base.metadata.tables.items():
        table.schema = original_schemas.get(table_name)

    engine.dispose()


@pytest.fixture(scope="session")
def session_factory(db_engine):
    """Session factory bound to e2e engine"""
    return sessionmaker(bind=db_engine)


@pytest.fixture(scope="session")
def seeded_db(db_engine, session_factory):
    """插入全部合成数据 (session 级, 只执行一次)"""
    session = session_factory()
    session.execute(text(f"SET search_path TO {E2E_SCHEMA}, public"))

    try:
        stocks = create_stocks(session)
        dates = create_trading_dates(session)
        daily = create_stock_daily(session, stocks, dates)
        factor_meta = create_factor_meta(session)
        factor_values = create_factor_values(session, stocks, dates, daily)
        session.commit()
        yield {
            "stocks": stocks,
            "dates": dates,
            "daily": daily,
            "factor_meta": factor_meta,
            "factor_values": factor_values,
        }
    finally:
        session.close()


@pytest.fixture(autouse=True)
def db_session(session_factory, seeded_db):
    """每个测试的直接 DB 访问 session (用于 fixture 操作)"""
    session = session_factory()
    session.execute(text(f"SET search_path TO {E2E_SCHEMA}, public"))
    yield session
    session.rollback()
    session.close()


def _make_get_session_factory(sf):
    """构造替代 src.common.db.get_session 的上下文管理器工厂

    每次调用创建新 session (设置 search_path 到 e2e_test), 退出时 commit.
    """
    @contextmanager
    def _override():
        session = sf()
        session.execute(text(f"SET search_path TO {E2E_SCHEMA}, public"))
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    return _override


def _make_get_db_factory(sf):
    """构造替代 src.common.db.get_db 的生成器工厂 (FastAPI Depends 兼容)."""
    def _override():
        session = sf()
        session.execute(text(f"SET search_path TO {E2E_SCHEMA}, public"))
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    return _override


@pytest.fixture
def client(session_factory, seeded_db):
    """FastAPI TestClient — 注入测试 DB session, mock 外部依赖"""
    override_get_session = _make_get_session_factory(session_factory)
    override_get_db = _make_get_db_factory(session_factory)

    with patch("src.common.db.get_session", override_get_session), \
         patch("src.common.db.get_db", override_get_db), \
         patch("src.api.main.init_database"), \
         patch("src.api.main.start_scheduler"), \
         patch("src.api.main.stop_scheduler"):
        from fastapi.testclient import TestClient
        from src.api.main import app
        with TestClient(app) as c:
            yield c
