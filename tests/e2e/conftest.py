"""E2E 测试核心 fixtures

两类测试共存:
  1. API E2E (合成数据) — e2e_test schema 隔离, 不依赖真实 QMT
  2. QMT E2E (真实终端) — @pytest.mark.qmt, 需 QMT 已登录

运行方式:
  pytest tests/e2e/ -m "not qmt"       # 仅 API E2E (CI)
  pytest tests/e2e/ -m qmt -v          # 仅 QMT E2E (本地)
  pytest tests/e2e/ -v                  # 全部
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
QMT_SCHEMA = "qmt_e2e_test"


@pytest.fixture(scope="session")
def db_engine():
    """连接现有 PostgreSQL, 创建隔离的 e2e_test schema

    通过 engine-level 事件自动设置 search_path, 确保所有 session
    (包括通过 from ... import get_session 直接引用的) 都指向 e2e_test schema。
    """
    engine = create_engine(
        settings.database.url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def _set_search_path(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute(f"SET search_path TO {E2E_SCHEMA}, public")
        cursor.close()

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


@pytest.fixture
def db_session(session_factory, seeded_db):
    """API E2E 测试用 DB session (需显式请求或通过 client fixture 间接使用)"""
    session = session_factory()
    session.execute(text(f"SET search_path TO {E2E_SCHEMA}, public"))
    yield session
    session.rollback()
    session.close()


@pytest.fixture
def client(session_factory, seeded_db, db_engine):
    """FastAPI TestClient — 注入测试 DB session, mock 外部依赖

    关键策略: 替换 src.common.db 的模块级 _engine 和 _SessionLocal,
    这样即使代码通过 ``from src.common.db import get_session`` 直接引用,
    get_session → get_session_factory → _SessionLocal 仍指向 e2e 引擎。
    engine-level "connect" 事件自动设置 search_path, 无需额外 patch。
    """
    import src.common.db as db_module

    with patch.object(db_module, "_engine", db_engine), \
         patch.object(db_module, "_SessionLocal", session_factory), \
         patch("src.api.main.init_database"), \
         patch("src.api.main.start_scheduler"), \
         patch("src.api.main.stop_scheduler"):
        from fastapi.testclient import TestClient
        from src.api.main import app
        with TestClient(app) as c:
            yield c


# ================================================================
# QMT E2E Fixtures — 需要真实 QMT 终端
# ================================================================

SAMPLE_STOCKS = ["600519.SH", "000001.SZ", "300750.SZ"]
SAMPLE_INDEX = "000300.SH"


@pytest.fixture(scope="session")
def qmt_client():
    """真实 QMTClient — 触发 xtquant 加载, 若未安装则跳过"""
    try:
        from src.data.qmt_client import QMTClient
        client = QMTClient()
        _ = client.xtdata
        return client
    except (ImportError, Exception) as exc:
        pytest.skip(f"QMTClient 不可用: {exc}")


@pytest.fixture(scope="session")
def qmt_trader():
    """真实 QMTTrader 只读连接 (不做下单/撤单)"""
    try:
        from src.trading.qmt_trader import QMTTrader
        trader = QMTTrader()
        if not trader.connect():
            pytest.skip("QMTTrader 连接失败")
        return trader
    except (ImportError, Exception) as exc:
        pytest.skip(f"QMTTrader 不可用: {exc}")


@pytest.fixture(scope="session")
def qmt_db_engine():
    """QMT E2E 专用 PostgreSQL 引擎 — 独立 schema, 不修改 Base.metadata

    使用 MetaData.to_metadata() 创建临时副本, 避免与 db_engine 的 schema 修改冲突。
    """
    from sqlalchemy import MetaData

    engine = create_engine(
        settings.database.url,
        pool_size=3,
        max_overflow=5,
        pool_pre_ping=True,
    )
    with engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {QMT_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {QMT_SCHEMA}"))
        conn.commit()

    qmt_meta = MetaData(schema=QMT_SCHEMA)
    for table in Base.metadata.sorted_tables:
        table.to_metadata(qmt_meta, schema=QMT_SCHEMA)
    qmt_meta.create_all(bind=engine)

    yield engine

    with engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {QMT_SCHEMA} CASCADE"))
        conn.commit()
    engine.dispose()


@pytest.fixture(scope="session")
def qmt_session_factory(qmt_db_engine):
    return sessionmaker(bind=qmt_db_engine)


@pytest.fixture
def qmt_db_session(qmt_session_factory):
    """QMT 测试用的独立 DB session"""
    session = qmt_session_factory()
    session.execute(text(f"SET search_path TO {QMT_SCHEMA}, public"))
    yield session
    session.rollback()
    session.close()


def make_qmt_get_session(sf):
    """构造 QMT E2E 用的 get_session 替代"""
    @contextmanager
    def _override():
        session = sf()
        session.execute(text(f"SET search_path TO {QMT_SCHEMA}, public"))
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
    return _override


@pytest.fixture(scope="session")
def sample_stock_list():
    return SAMPLE_STOCKS


@pytest.fixture(scope="session")
def sample_index_code():
    return SAMPLE_INDEX
