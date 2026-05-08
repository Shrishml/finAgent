"""Single-user SQLite storage for parsed financial data."""
import json
import sqlite3
from dataclasses import asdict
from datetime import date
from pathlib import Path

from finagent.models.mf import MFHolding, MFTransaction

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
    # Migration: add access_status to users
    try:
        conn.execute("ALTER TABLE users ADD COLUMN access_status TEXT DEFAULT 'waitlist'")
        # Grandfather existing users
        conn.execute("UPDATE users SET access_status = 'active' WHERE access_status IS NULL OR access_status = 'waitlist'")
    except sqlite3.OperationalError:
        pass  # Column already exists
    # Invite codes table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invite_codes (
            code TEXT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            max_uses INTEGER DEFAULT 1,
            used_count INTEGER DEFAULT 0,
            note TEXT
        )
    """)
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


def get_user_access_status(user_id: int) -> str:
    """Returns 'waitlist', 'active', or 'blocked'."""
    conn = _get_conn()
    row = conn.execute("SELECT access_status FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return (row[0] if row and row[0] else "waitlist")


def set_user_access_status(user_id: int, status: str) -> None:
    """Admin: change user access status."""
    conn = _get_conn()
    conn.execute("UPDATE users SET access_status = ? WHERE id = ?", (status, user_id))
    conn.commit()
    conn.close()


def list_waitlist_users() -> list[dict]:
    """List all users on waitlist."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT id, email, name, created_at FROM users WHERE access_status = 'waitlist' ORDER BY created_at"
    ).fetchall()
    conn.close()
    return [{"id": r[0], "email": r[1], "name": r[2], "created_at": r[3]} for r in rows]


def redeem_invite_code(code: str, user_id: int) -> bool:
    """Redeem an invite code. Returns True if successful."""
    conn = _get_conn()
    row = conn.execute("SELECT max_uses, used_count FROM invite_codes WHERE code = ?", (code,)).fetchone()
    if not row or row[1] >= row[0]:
        conn.close()
        return False
    conn.execute("UPDATE invite_codes SET used_count = used_count + 1 WHERE code = ?", (code,))
    conn.execute("UPDATE users SET access_status = 'active' WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True


def create_invite_codes(count: int = 5, max_uses: int = 1, note: str = "") -> list[str]:
    """Generate invite codes. Returns list of code strings."""
    import secrets
    conn = _get_conn()
    codes = []
    for _ in range(count):
        code = f"ARTH-{secrets.token_hex(3).upper()}"
        conn.execute("INSERT INTO invite_codes (code, max_uses, note) VALUES (?, ?, ?)", (code, max_uses, note))
        codes.append(code)
    conn.commit()
    conn.close()
    return codes


def list_invite_codes() -> list[dict]:
    """List all invite codes with usage stats."""
    conn = _get_conn()
    rows = conn.execute("SELECT code, max_uses, used_count, note, created_at FROM invite_codes").fetchall()
    conn.close()
    return [{"code": r[0], "max_uses": r[1], "used_count": r[2], "note": r[3], "created_at": r[4]} for r in rows]


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
