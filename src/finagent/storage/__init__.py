"""Storage layer - async database operations with SQLAlchemy ORM."""
import sqlite3
from pathlib import Path

# Database infrastructure
from finagent.storage.database import get_db, get_engine, init_db, reset_engine, close_engine

# User operations
from finagent.storage.user_ops import get_or_create_user, get_user_name

# Asset operations (unified asset layer)
from finagent.storage.asset_ops import (
    reconcile_and_save,
    load_mf_assets,
    clear_mf_assets,
    save_assets,
    load_assets,
    clear_assets,
)

# Legacy holding operations
from finagent.storage.holding_ops import save_holdings, load_holdings, clear_holdings

# Goal operations
from finagent.storage.goal_ops import save_goal, load_goals, delete_goal, clear_goals

# Profile operations
from finagent.storage.profile_ops import save_profile, load_profile, update_profile, clear_profile

# NAV cache operations
from finagent.storage.nav_ops import save_nav_cache, get_cached_nav

# Conversation operations
from finagent.storage.conversation_ops import save_message, load_conversation, clear_conversation

# Snapshot operations
from finagent.storage.snapshot_ops import (
    save_snapshot,
    get_latest_snapshot,
    should_update_snapshot,
    clear_snapshots,
)

# Backward compatibility: mutable module-level paths for test monkeypatching
_DB_DIR = Path(__file__).parent.parent.parent / "data"
_DB_PATH = _DB_DIR / "finagent.db"


def _get_conn() -> sqlite3.Connection:
    """Legacy connection getter for backward compatibility with tests."""
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(str(_DB_PATH))


__all__ = [
    # Database
    "get_db",
    "get_engine",
    "init_db",
    "reset_engine",
    "close_engine",
    # User
    "get_or_create_user",
    "get_user_name",
    # Assets
    "reconcile_and_save",
    "load_mf_assets",
    "clear_mf_assets",
    "save_assets",
    "load_assets",
    "clear_assets",
    # Holdings (legacy)
    "save_holdings",
    "load_holdings",
    "clear_holdings",
    # Goals
    "save_goal",
    "load_goals",
    "delete_goal",
    "clear_goals",
    # Profile
    "save_profile",
    "load_profile",
    "update_profile",
    "clear_profile",
    # NAV
    "save_nav_cache",
    "get_cached_nav",
    # Conversation
    "save_message",
    "load_conversation",
    "clear_conversation",
    # Snapshots
    "save_snapshot",
    "get_latest_snapshot",
    "should_update_snapshot",
    "clear_snapshots",
    # Backward compat
    "_DB_DIR",
    "_DB_PATH",
    "_get_conn",
]
