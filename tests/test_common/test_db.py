"""Tests for src/common/db.py

Uses real PostgreSQL with an isolated schema (ut_db_test) to match production.
"""
import pytest
from unittest.mock import patch
from sqlalchemy import Column, Integer, String, text, create_engine, inspect
from sqlalchemy.orm import Session

from src.common.config import settings

UT_SCHEMA = "ut_db_test"

_pg_available = None


def _check_pg():
    global _pg_available
    if _pg_available is not None:
        return _pg_available
    try:
        engine = create_engine(settings.database.url, pool_pre_ping=True)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        engine.dispose()
        _pg_available = True
    except Exception:
        _pg_available = False
    return _pg_available


pytestmark = pytest.mark.skipif(
    not _check_pg(), reason="PostgreSQL not available"
)


class TestDatabase:
    """Tests use a dedicated PostgreSQL schema to avoid polluting other data."""

    @pytest.fixture(autouse=True)
    def _reset_db_module(self):
        """Reset the module-level engine and session factory before each test."""
        import src.common.db as db_mod
        db_mod._engine = None
        db_mod._SessionLocal = None
        yield
        if db_mod._engine is not None:
            db_mod._engine.dispose()
        db_mod._engine = None
        db_mod._SessionLocal = None

    @pytest.fixture
    def patched_settings(self):
        with patch("src.common.db.settings") as mock_settings:
            mock_settings.database.url = settings.database.url
            mock_settings.database.pool_size = 2
            mock_settings.database.max_overflow = 3
            mock_settings.database.pool_timeout = 10
            mock_settings.database.pool_recycle = 1800
            yield mock_settings

    def test_get_engine_creates_engine(self, patched_settings):
        from src.common.db import get_engine
        engine = get_engine()
        assert engine is not None
        assert "postgresql" in str(engine.url)

    def test_get_engine_returns_singleton(self, patched_settings):
        from src.common.db import get_engine
        e1 = get_engine()
        e2 = get_engine()
        assert e1 is e2

    def test_get_session_factory_returns_sessionmaker(self, patched_settings):
        from src.common.db import get_session_factory
        factory = get_session_factory()
        assert callable(factory)

    def test_get_session_factory_returns_singleton(self, patched_settings):
        from src.common.db import get_session_factory
        f1 = get_session_factory()
        f2 = get_session_factory()
        assert f1 is f2

    def test_get_session_commits_on_success(self, patched_settings):
        from src.common.db import get_session, get_engine, Base

        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {UT_SCHEMA} CASCADE"))
            conn.execute(text(f"CREATE SCHEMA {UT_SCHEMA}"))
            conn.commit()

        try:
            class DummyCommit(Base):
                __tablename__ = "dummy_commit_test"
                __table_args__ = {"schema": UT_SCHEMA}
                id = Column(Integer, primary_key=True)
                name = Column(String(50))

            DummyCommit.__table__.create(bind=engine, checkfirst=True)

            with get_session() as session:
                session.execute(text(f"SET search_path TO {UT_SCHEMA}, public"))
                session.add(DummyCommit(id=1, name="test"))

            with get_session() as session:
                session.execute(text(f"SET search_path TO {UT_SCHEMA}, public"))
                result = session.execute(
                    text(f"SELECT name FROM {UT_SCHEMA}.dummy_commit_test WHERE id=1")
                )
                row = result.fetchone()
                assert row is not None
                assert row[0] == "test"
        finally:
            with engine.connect() as conn:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {UT_SCHEMA} CASCADE"))
                conn.commit()

    def test_get_session_rollbacks_on_error(self, patched_settings):
        from src.common.db import get_session, get_engine, Base

        engine = get_engine()
        with engine.connect() as conn:
            conn.execute(text(f"DROP SCHEMA IF EXISTS {UT_SCHEMA} CASCADE"))
            conn.execute(text(f"CREATE SCHEMA {UT_SCHEMA}"))
            conn.commit()

        try:
            class DummyRollback(Base):
                __tablename__ = "dummy_rollback_test"
                __table_args__ = {"schema": UT_SCHEMA}
                id = Column(Integer, primary_key=True)
                name = Column(String(50))

            DummyRollback.__table__.create(bind=engine, checkfirst=True)

            with get_session() as session:
                session.execute(text(f"SET search_path TO {UT_SCHEMA}, public"))
                session.add(DummyRollback(id=1, name="committed"))

            with pytest.raises(RuntimeError):
                with get_session() as session:
                    session.execute(text(f"SET search_path TO {UT_SCHEMA}, public"))
                    session.add(DummyRollback(id=2, name="should_rollback"))
                    raise RuntimeError("force rollback")

            with get_session() as session:
                result = session.execute(
                    text(f"SELECT count(*) FROM {UT_SCHEMA}.dummy_rollback_test")
                )
                assert result.scalar() == 1
        finally:
            with engine.connect() as conn:
                conn.execute(text(f"DROP SCHEMA IF EXISTS {UT_SCHEMA} CASCADE"))
                conn.commit()

    def test_get_session_closes_session(self, patched_settings):
        from src.common.db import get_session
        with get_session() as session:
            assert isinstance(session, Session)

    def test_init_database_calls_create_all(self, patched_settings):
        from src.common.db import init_database, Base, get_engine
        get_engine()
        with patch.object(Base.metadata, "create_all") as mock_create_all:
            init_database()
            mock_create_all.assert_called_once()

    def test_get_db_yields_session(self, patched_settings):
        """get_db generator (FastAPI DI) delegates to get_session."""
        from src.common.db import get_db, get_engine
        get_engine()
        gen = get_db()
        session = next(gen)
        assert isinstance(session, Session)
        try:
            gen.send(None)
        except StopIteration:
            pass

    def test_check_db_connection(self, patched_settings):
        from src.common.db import check_db_connection, get_engine
        get_engine()
        assert check_db_connection() is True
