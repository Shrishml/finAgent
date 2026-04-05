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
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            folio TEXT,
            scheme_name TEXT,
            data JSON NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(folio, scheme_name)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nav_cache (
            amfi_code TEXT PRIMARY KEY,
            nav REAL,
            expense_ratio REAL DEFAULT 0,
            scheme_name TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    return conn


def save_holdings(holdings: list[MFHolding]):
    """Upsert holdings — replaces existing entries for same folio+scheme."""
    conn = _get_conn()
    for h in holdings:
        data = asdict(h)
        # Convert date objects to strings for JSON serialization
        for t in data.get("transactions", []):
            if hasattr(t.get("date"), "isoformat"):
                t["date"] = t["date"].isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO holdings (folio, scheme_name, data) VALUES (?, ?, ?)",
            (h.folio, h.scheme_name, json.dumps(data)),
        )
    conn.commit()
    conn.close()


def load_holdings() -> list[MFHolding]:
    """Load all stored holdings."""
    conn = _get_conn()
    rows = conn.execute("SELECT data FROM holdings").fetchall()
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
            transactions=txns,
        ))
    return holdings


def clear_holdings():
    """Clear all holdings (for re-upload)."""
    conn = _get_conn()
    conn.execute("DELETE FROM holdings")
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
