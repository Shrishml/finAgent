"""Single-user SQLite storage for parsed financial data."""
import json
import sqlite3
from dataclasses import asdict
from datetime import date
from pathlib import Path

from finagent.models.mf import MFHolding, MFTransaction
from finagent.models.goal import Goal
from finagent.models.profile import UserProfile

_DB_DIR = Path(__file__).parent.parent.parent / "data"
_DB_PATH = _DB_DIR / "finagent.db"


def _get_conn() -> sqlite3.Connection:
    _DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            google_id TEXT UNIQUE NOT NULL,
            email TEXT,
            name TEXT,
            picture TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            folio TEXT,
            scheme_name TEXT,
            data JSON NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, folio, scheme_name)
        )
    """)
    # Migration: add user_id column to existing holdings table
    try:
        conn.execute("ALTER TABLE holdings ADD COLUMN user_id INTEGER")
    except sqlite3.OperationalError:
        pass  # Column already exists
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nav_cache (
            amfi_code TEXT PRIMARY KEY,
            nav REAL,
            expense_ratio REAL DEFAULT 0,
            scheme_name TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nav_history (
            amfi_code TEXT,
            date TEXT,
            nav REAL,
            PRIMARY KEY (amfi_code, date)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nav_history_meta (
            amfi_code TEXT PRIMARY KEY,
            last_fetched TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            template TEXT NOT NULL,
            target_amount REAL NOT NULL,
            target_date TEXT NOT NULL,
            linked_folios JSON DEFAULT '[]',
            growth_rate REAL DEFAULT 0.10,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            user_id INTEGER PRIMARY KEY,
            data JSON NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata JSON DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, created_at)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            snapshot TEXT NOT NULL,
            trigger TEXT NOT NULL DEFAULT 'onboarding',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_snap_user ON user_snapshots(user_id, created_at)")
    conn.commit()
    return conn


def get_or_create_user(google_id: str, email: str = "", name: str = "", picture: str = "") -> int:
    """Get existing user or create new one. Returns user_id."""
    conn = _get_conn()
    row = conn.execute("SELECT id FROM users WHERE google_id = ?", (google_id,)).fetchone()
    if row:
        conn.execute("UPDATE users SET email=?, name=?, picture=? WHERE id=?", (email, name, picture, row[0]))
        conn.commit()
        conn.close()
        return row[0]
    cur = conn.execute("INSERT INTO users (google_id, email, name, picture) VALUES (?, ?, ?, ?)", (google_id, email, name, picture))
    conn.commit()
    uid = cur.lastrowid
    conn.close()
    return uid


def get_user_name(user_id: int) -> str:
    """Get user's display name by user_id."""
    conn = _get_conn()
    row = conn.execute("SELECT name FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row and row[0] else ""


def _merge_transactions(existing: list[dict], incoming: list[dict]) -> list[dict]:
    """Merge transaction lists, dedup by (date, amount, units)."""
    seen = {(t.get("date"), t.get("amount"), t.get("units")) for t in existing}
    merged = list(existing)
    for t in incoming:
        key = (t.get("date"), t.get("amount"), t.get("units"))
        if key not in seen:
            seen.add(key)
            merged.append(t)
    merged.sort(key=lambda t: t.get("date", ""))
    return merged


def save_holdings(holdings: list[MFHolding], user_id: int | None = None, merge: bool = False):
    """Upsert holdings. If merge=True, merge transactions with existing data."""
    conn = _get_conn()
    for h in holdings:
        data = asdict(h)
        for t in data.get("transactions", []):
            if hasattr(t.get("date"), "isoformat"):
                t["date"] = t["date"].isoformat()

        if merge:
            row = conn.execute(
                "SELECT data FROM holdings WHERE user_id = ? AND folio = ? AND scheme_name = ?",
                (user_id, h.folio, h.scheme_name),
            ).fetchone()
            if row:
                old = json.loads(row[0])
                data["transactions"] = _merge_transactions(
                    old.get("transactions", []), data.get("transactions", [])
                )

        conn.execute(
            "INSERT OR REPLACE INTO holdings (user_id, folio, scheme_name, data) VALUES (?, ?, ?, ?)",
            (user_id, h.folio, h.scheme_name, json.dumps(data)),
        )
    conn.commit()
    conn.close()


def load_holdings(user_id: int | None = None) -> list[MFHolding]:
    """Load stored holdings for a user (or all if no user_id)."""
    conn = _get_conn()
    if user_id is not None:
        rows = conn.execute("SELECT data FROM holdings WHERE user_id = ?", (user_id,)).fetchall()
    else:
        rows = conn.execute("SELECT data FROM holdings WHERE user_id IS NULL").fetchall()
    conn.close()
    holdings = []
    for (data_json,) in rows:
        d = json.loads(data_json)
        txns = [
            MFTransaction(
                date=date.fromisoformat(t["date"]) if isinstance(t.get("date"), str) else t.get("date", date.today()),
                description=t.get("description", ""),
                amount=float(t.get("amount", 0)),
                units=t.get("units"),
                nav=t.get("nav"),
                balance=t.get("balance"),
                type=t.get("type", ""),
            )
            for t in d.get("transactions", [])
        ]
        holdings.append(MFHolding(
            scheme_name=d["scheme_name"], folio=d["folio"], amc=d["amc"],
            isin=d.get("isin", ""), amfi_code=d.get("amfi_code", ""),
            plan=d.get("plan", ""), rta=d.get("rta", ""),
            units=d.get("units", 0), nav=d.get("nav", 0),
            current_value=d.get("current_value", 0),
            invested_value=d.get("invested_value", 0),
            expense_ratio=d.get("expense_ratio", 0),
            annual_expense=d.get("annual_expense", 0),
            xirr=d.get("xirr", 0), tax_section=d.get("tax_section", ""),
            category=d.get("category", ""),
            nav_date=d.get("nav_date", ""),
            day_change=d.get("day_change", 0),
            day_change_pct=d.get("day_change_pct", 0),
            morningstar=d.get("morningstar", 0),
            aum=d.get("aum", 0),
            risk_label=d.get("risk_label", ""),
            transactions=txns,
        ))
    return [h for h in holdings if h.current_value > 0]


def clear_holdings(user_id: int | None = None):
    """Clear holdings for a user (or legacy null-user holdings)."""
    conn = _get_conn()
    if user_id is not None:
        conn.execute("DELETE FROM holdings WHERE user_id = ?", (user_id,))
    else:
        conn.execute("DELETE FROM holdings WHERE user_id IS NULL")
    conn.commit()
    conn.close()


def save_nav_cache(amfi_code: str, nav: float, scheme_name: str = "", expense_ratio: float = 0):
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO nav_cache (amfi_code, nav, expense_ratio, scheme_name, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
        (amfi_code, nav, expense_ratio, scheme_name),
    )
    conn.commit()
    conn.close()


def get_cached_nav(amfi_code: str) -> dict | None:
    """Get cached data if less than 24h old. Returns {nav, expense_ratio} or None."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT nav, expense_ratio FROM nav_cache WHERE amfi_code = ? AND updated_at > datetime('now', '-24 hours')",
        (amfi_code,),
    ).fetchone()
    conn.close()
    return {"nav": row[0], "expense_ratio": row[1]} if row else None


# --- Goals ---

def save_goal(goal: Goal) -> int:
    """Insert or update a goal. Returns goal id."""
    conn = _get_conn()
    folios_json = json.dumps(goal.linked_folios)
    if goal.id:
        conn.execute(
            "UPDATE goals SET name=?, template=?, target_amount=?, target_date=?, linked_folios=?, growth_rate=? WHERE id=? AND user_id=?",
            (goal.name, goal.template, goal.target_amount, goal.target_date, folios_json, goal.growth_rate, goal.id, goal.user_id),
        )
        conn.commit()
        conn.close()
        return goal.id
    cur = conn.execute(
        "INSERT INTO goals (user_id, name, template, target_amount, target_date, linked_folios, growth_rate) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (goal.user_id, goal.name, goal.template, goal.target_amount, goal.target_date, folios_json, goal.growth_rate),
    )
    conn.commit()
    gid = cur.lastrowid
    conn.close()
    return gid


def load_goals(user_id: int) -> list[Goal]:
    """Load all goals for a user."""
    conn = _get_conn()
    rows = conn.execute("SELECT id, user_id, name, template, target_amount, target_date, linked_folios, growth_rate, created_at FROM goals WHERE user_id=?", (user_id,)).fetchall()
    conn.close()
    return [
        Goal(id=r[0], user_id=r[1], name=r[2], template=r[3], target_amount=r[4], target_date=r[5],
             linked_folios=json.loads(r[6]) if r[6] else [], growth_rate=r[7], created_at=r[8] or "")
        for r in rows
    ]


def delete_goal(goal_id: int, user_id: int) -> bool:
    """Delete a goal. Returns True if deleted."""
    conn = _get_conn()
    cur = conn.execute("DELETE FROM goals WHERE id=? AND user_id=?", (goal_id, user_id))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted


def clear_goals(user_id: int):
    """Clear all goals for a user."""
    conn = _get_conn()
    conn.execute("DELETE FROM goals WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()


# --- User Profile ---

def save_profile(profile: UserProfile):
    """Upsert user profile as JSON blob."""
    conn = _get_conn()
    from dataclasses import asdict
    data = {k: v for k, v in asdict(profile).items() if k != "user_id"}
    conn.execute(
        "INSERT OR REPLACE INTO user_profiles (user_id, data, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
        (profile.user_id, json.dumps(data)),
    )
    conn.commit()
    conn.close()


def load_profile(user_id: int) -> UserProfile | None:
    """Load user profile. Returns None if no profile exists."""
    conn = _get_conn()
    row = conn.execute("SELECT data FROM user_profiles WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = json.loads(row[0])
    from dataclasses import fields as dc_fields, MISSING
    kwargs = {"user_id": user_id}
    for f in dc_fields(UserProfile):
        if f.name == "user_id":
            continue
        if f.default is not MISSING:
            kwargs[f.name] = d.get(f.name, f.default)
        else:
            kwargs[f.name] = d.get(f.name, f.default_factory())
    return UserProfile(**kwargs)


def update_profile(user_id: int, updates: dict) -> UserProfile | None:
    """Partial update — merge updates into existing profile."""
    profile = load_profile(user_id)
    if not profile:
        profile = UserProfile(user_id=user_id)
    for key, value in updates.items():
        if hasattr(profile, key):
            setattr(profile, key, value)
    save_profile(profile)
    return profile


# --- Snapshots ---


def save_snapshot(user_id: int, snapshot: str, trigger: str = "onboarding") -> int:
    """Save a new snapshot. Returns snapshot id."""
    conn = _get_conn()
    cur = conn.execute(
        "INSERT INTO user_snapshots (user_id, snapshot, trigger) VALUES (?, ?, ?)",
        (user_id, snapshot, trigger),
    )
    conn.commit()
    return cur.lastrowid


def get_latest_snapshot(user_id: int) -> dict | None:
    """Get most recent snapshot for user."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, snapshot, trigger, created_at FROM user_snapshots WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return {"id": row[0], "snapshot": row[1], "trigger": row[2], "created_at": row[3]}


def should_update_snapshot(user_id: int, profile_updated_at: str | None = None) -> tuple[bool, str]:
    """Check if snapshot needs regeneration. Returns (should_update, reason)."""
    from datetime import datetime, timedelta
    snap = get_latest_snapshot(user_id)
    profile = load_profile(user_id)
    if not profile:
        return False, ""
    has_data = profile.monthly_income > 0 or profile.monthly_expenses > 0 or profile.age > 0
    if not snap:
        return (True, "first_snapshot") if has_data else (False, "")
    snap_time = datetime.fromisoformat(snap["created_at"].replace("Z", "+00:00")) if isinstance(snap["created_at"], str) else snap["created_at"]
    if isinstance(snap_time, str):
        snap_time = datetime.fromisoformat(snap_time)
    now = datetime.utcnow()
    if (now - snap_time.replace(tzinfo=None)).days > 30:
        return True, "stale"
    return False, ""


# --- Conversations ---

_MAX_MESSAGES_PER_USER = 50


def save_message(user_id: int, role: str, content: str, metadata: dict | None = None):
    """Save a conversation message. Auto-prunes to keep last N messages."""
    conn = _get_conn()
    conn.execute(
        "INSERT INTO conversations (user_id, role, content, metadata) VALUES (?, ?, ?, ?)",
        (user_id, role, content, json.dumps(metadata or {})),
    )
    # Prune old messages
    conn.execute("""
        DELETE FROM conversations WHERE user_id = ? AND id NOT IN (
            SELECT id FROM conversations WHERE user_id = ? ORDER BY created_at DESC LIMIT ?
        )
    """, (user_id, user_id, _MAX_MESSAGES_PER_USER))
    conn.commit()
    conn.close()


def load_conversation(user_id: int, limit: int = 20) -> list[dict]:
    """Load recent conversation messages, oldest first."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT role, content, metadata, created_at FROM conversations WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return [
        {"role": r[0], "content": r[1], "metadata": json.loads(r[2]) if r[2] else {}, "created_at": r[3]}
        for r in reversed(rows)  # reverse to get oldest-first
    ]


def clear_snapshots(user_id: int):
    conn = _get_conn()
    conn.execute("DELETE FROM user_snapshots WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def clear_conversation(user_id: int):
    """Clear all conversation history for a user."""
    conn = _get_conn()
    conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def clear_profile(user_id: int):
    """Clear user profile (onboarding data)."""
    conn = _get_conn()
    conn.execute("DELETE FROM user_profiles WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
