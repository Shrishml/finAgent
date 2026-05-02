import sys
import os
from pathlib import Path

import pytest

# Ensure finagent package is importable from any test subfolder
sys.path.insert(0, str(Path(__file__).parent.parent))


def async_return(value):
    """Create an async function that returns a value. For use in monkeypatch."""
    async def _inner(*args, **kwargs):
        return value
    return _inner


@pytest.fixture(autouse=True)
def setup_test_db(tmp_path, monkeypatch):
    """Set up a temporary SQLite database for each test."""
    import finagent.storage as storage_mod
    from finagent.storage import database as db_mod

    # Legacy paths (for backward compat)
    monkeypatch.setattr(storage_mod, "_DB_DIR", tmp_path)
    monkeypatch.setattr(storage_mod, "_DB_PATH", tmp_path / "test.db")

    # SQLAlchemy config - use temp directory
    test_db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", test_db_url)

    # Reset engine so it picks up new URL
    # Note: actual variable is _async_session_factory, not _session_factory
    db_mod._engine = None
    db_mod._async_session_factory = None

    # Initialize tables synchronously using asyncio
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.run_until_complete(db_mod.init_db())

    yield

    # Cleanup
    db_mod._engine = None
    db_mod._async_session_factory = None
