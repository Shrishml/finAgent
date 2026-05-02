"""Async database engine and session management for SQLAlchemy ORM."""
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from finagent.config import get_config

_DB_DIR = Path(__file__).parent.parent.parent / "data"
_DEFAULT_DB_PATH = _DB_DIR / "finagent.db"

_engine = None
_async_session_factory = None


def _get_database_url() -> str:
    """Get async database URL from env, config, or use default SQLite."""
    import os
    # Check environment variable first (useful for testing)
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        cfg = get_config()
        db_cfg = cfg.get("database", {})
        url = db_cfg.get("url", "")

    if url:
        # Convert sync URLs to async driver URLs
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://")
        elif url.startswith("sqlite:///"):
            return url.replace("sqlite:///", "sqlite+aiosqlite:///")
        return url

    _DB_DIR.mkdir(parents=True, exist_ok=True)
    return f"sqlite+aiosqlite:///{_DEFAULT_DB_PATH}"


def get_engine():
    """Get or create the async SQLAlchemy engine (singleton)."""
    global _engine
    if _engine is None:
        url = _get_database_url()
        connect_args = {}
        if "sqlite" in url:
            connect_args["check_same_thread"] = False
        _engine = create_async_engine(url, connect_args=connect_args)
    return _engine


def get_session_factory() -> async_sessionmaker:
    """Get or create the async session factory (singleton)."""
    global _async_session_factory
    if _async_session_factory is None:
        _async_session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False
        )
    return _async_session_factory


@asynccontextmanager
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Async context manager for database sessions. Auto-commits on success, rollback on error."""
    async with get_session_factory()() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def init_db():
    """Create all tables. Call once at app startup."""
    from finagent.storage.models import Base
    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def reset_engine():
    """Reset engine and session factory. Useful for testing."""
    global _engine, _async_session_factory
    if _engine:
        # Note: For async engine, disposal should be awaited in async context
        pass
    _engine = None
    _async_session_factory = None


async def close_engine():
    """Properly close the async engine."""
    global _engine
    if _engine:
        await _engine.dispose()
    _engine = None
