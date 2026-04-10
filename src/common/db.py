"""数据库连接管理

- 连接池: QueuePool + pre_ping + recycle 防止断连
- 启动重试: 指数退避, 容器编排时 DB 可能尚未就绪
- 会话: context manager 自动 commit/rollback/close
"""
import time
from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool

from .config import settings
from .logger import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """ORM 模型基类 — SQLAlchemy 2.x DeclarativeBase"""
    pass

_engine = None
_SessionLocal = None

_MAX_STARTUP_RETRIES = 5
_STARTUP_BACKOFF_BASE = 2  # seconds


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.database.url,
            poolclass=QueuePool,
            pool_size=settings.database.pool_size,
            max_overflow=settings.database.max_overflow,
            pool_timeout=settings.database.pool_timeout,
            pool_recycle=settings.database.pool_recycle,
            pool_pre_ping=True,
            echo=False,
        )
    return _engine


def get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=get_engine()
        )
    return _SessionLocal


@contextmanager
def get_session() -> Generator[Session, None, None]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_db_connection() -> bool:
    """探测数据库是否可达, 用于 /health 端点"""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖注入 — 桥接 get_session 上下文管理器为 Depends 生成器.

    patch get_session 即可同时影响 get_db, 便于测试替换.
    """
    with get_session() as session:
        yield session


def init_database():
    """建表, 带启动重试 (容器场景下 DB 可能还未就绪)"""
    for attempt in range(1, _MAX_STARTUP_RETRIES + 1):
        try:
            engine = get_engine()
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            Base.metadata.create_all(bind=engine)
            logger.info("数据库初始化完成")
            return
        except Exception as e:
            wait = _STARTUP_BACKOFF_BASE ** attempt
            logger.warning(
                f"数据库连接失败 (第{attempt}次): {e} — {wait}s 后重试"
            )
            if attempt == _MAX_STARTUP_RETRIES:
                logger.error("数据库连接重试耗尽, 启动失败")
                raise
            time.sleep(wait)
