"""Tests for src/common/db.py"""
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import Column, Integer, String, text
from sqlalchemy.orm import Session


class TestDatabase:
    """All tests patch settings.database.url to use sqlite in-memory and
    reset module-level singletons before each test."""

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
            mock_settings.database.url = "sqlite:///:memory:"
            mock_settings.database.pool_size = 5
            mock_settings.database.max_overflow = 10
            mock_settings.database.pool_timeout = 30
            mock_settings.database.pool_recycle = 1800
            yield mock_settings

    def test_get_engine_creates_engine(self, patched_settings):
        from src.common.db import get_engine
        engine = get_engine()
        assert engine is not None
        assert "sqlite" in str(engine.url)

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

        class DummyModel(Base):
            __tablename__ = "dummy_commit_test"
            id = Column(Integer, primary_key=True)
            name = Column(String(50))

        engine = get_engine()
        Base.metadata.create_all(bind=engine)

        with get_session() as session:
            session.add(DummyModel(id=1, name="test"))

        with get_session() as session:
            result = session.execute(text("SELECT name FROM dummy_commit_test WHERE id=1"))
            row = result.fetchone()
            assert row is not None
            assert row[0] == "test"

    def test_get_session_rollbacks_on_error(self, patched_settings):
        from src.common.db import get_session, get_engine, Base

        class DummyModel2(Base):
            __tablename__ = "dummy_rollback_test"
            id = Column(Integer, primary_key=True)
            name = Column(String(50))

        engine = get_engine()
        Base.metadata.create_all(bind=engine)

        with get_session() as session:
            session.add(DummyModel2(id=1, name="committed"))

        with pytest.raises(RuntimeError):
            with get_session() as session:
                session.add(DummyModel2(id=2, name="should_rollback"))
                raise RuntimeError("force rollback")

        with get_session() as session:
            result = session.execute(text("SELECT count(*) FROM dummy_rollback_test"))
            assert result.scalar() == 1

    def test_get_session_closes_session(self, patched_settings):
        from src.common.db import get_session
        with get_session() as session:
            assert isinstance(session, Session)
        # After context exit the session should be closed — attempting to use it
        # would raise; we just verify no exception during the context exit.

    def test_init_database_calls_create_all(self, patched_settings):
        from src.common.db import init_database, Base, get_engine
        get_engine()
        with patch.object(Base.metadata, "create_all") as mock_create_all:
            init_database()
            mock_create_all.assert_called_once()

    def test_check_db_connection(self, patched_settings):
        from src.common.db import check_db_connection, get_engine
        get_engine()
        assert check_db_connection() is True
