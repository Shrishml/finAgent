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


def save_holdings(holdings: list[MFHolding], user_id: int | None = None):
    """Upsert holdings — replaces existing entries for same folio+scheme."""
    conn = _get_conn()
    for h in holdings:
        data = asdict(h)
        for t in data.get("transactions", []):
            if hasattr(t.get("date"), "isoformat"):
                t["date"] = t["date"].isoformat()
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
    return holdings


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
