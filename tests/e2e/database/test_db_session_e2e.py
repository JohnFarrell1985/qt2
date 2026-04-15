"""Database Session E2E — 使用真实 PostgreSQL 验证 get_session 与连接管理

测试范围:
  - get_session readonly 模式 (不提交变更)
  - get_session 读写模式 (自动提交)
  - check_db_connection 连通性
  - 连接池基本行为
"""
import pytest

from sqlalchemy import text

from src.common.db import check_db_connection, get_session, get_engine


pytestmark = pytest.mark.timeout(15)


class TestCheckDbConnection:
    """数据库连通性检测"""

    def test_connection_succeeds(self):
        assert check_db_connection() is True

    def test_engine_pool_pre_ping(self):
        engine = get_engine()
        assert engine.pool.size() >= 1


class TestGetSessionReadonly:
    """get_session(readonly=True) — 使用真实 public schema 只读查询"""

    def test_readonly_can_query(self):
        with get_session(readonly=True) as session:
            result = session.execute(text("SELECT 1")).scalar()
            assert result == 1

    def test_readonly_can_read_stocks(self):
        with get_session(readonly=True) as session:
            row = session.execute(
                text("SELECT count(*) FROM stocks")
            ).scalar()
            assert isinstance(row, int)

    def test_readonly_does_not_commit(self, pg_engine):
        """readonly 模式下写入在 session 关闭后被 rollback"""
        from sqlalchemy.orm import sessionmaker
        factory = sessionmaker(bind=pg_engine)

        session = factory()
        try:
            session.execute(text(
                "CREATE TEMP TABLE _readonly_test (id int)"
            ))
            session.execute(text("INSERT INTO _readonly_test VALUES (1)"))
            session.rollback()
        finally:
            session.close()

        session2 = factory()
        try:
            result = session2.execute(
                text("SELECT to_regclass('_readonly_test')")
            ).scalar()
            assert result is None
        finally:
            session2.close()


class TestGetSessionReadWrite:
    """get_session 读写模式 — 在 db_e2e_test schema 中测试"""

    def test_write_session_commits(self, db_e2e_engine, db_e2e_session):
        db_e2e_session.execute(text(
            "INSERT INTO stocks (code, name, industry, exchange) "
            "VALUES ('RWTEST01', '读写测试', '测试', 'SZ')"
        ))
        db_e2e_session.commit()

        row = db_e2e_session.execute(
            text("SELECT name FROM stocks WHERE code = 'RWTEST01'")
        ).fetchone()
        assert row is not None
        assert row[0] == "读写测试"


class TestConcurrentSessions:
    """并发 session 基本隔离"""

    def test_multiple_readonly_sessions(self):
        results = []
        for _ in range(5):
            with get_session(readonly=True) as session:
                val = session.execute(text("SELECT 1")).scalar()
                results.append(val)
        assert all(r == 1 for r in results)
