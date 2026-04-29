"""Single-user SQLite storage for parsed financial data."""
import json
import logging
import sqlite3
from dataclasses import asdict
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from finagent.models.mf import MFHolding, MFTransaction
from finagent.models.goal import Goal
from finagent.models.profile import UserProfile

log = logging.getLogger("finagent.storage")

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
            status TEXT DEFAULT 'active',
            description TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Migration: add status column to existing goals table
    try:
        conn.execute("ALTER TABLE goals ADD COLUMN status TEXT DEFAULT 'active'")
    except sqlite3.OperationalError:
        pass
    # Migration: add description column to existing goals table
    try:
        conn.execute("ALTER TABLE goals ADD COLUMN description TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            asset_type TEXT NOT NULL,
            data TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_assets_user ON user_assets(user_id, asset_type)")
    # Migration: add source tracking columns to user_assets
    for col, default in [("source", "'declared'"), ("source_detail", "'chat'"), ("verified_at", "NULL")]:
        try:
            conn.execute(f"ALTER TABLE user_assets ADD COLUMN {col} TEXT DEFAULT {default}")
        except sqlite3.OperationalError:
            pass  # Column already exists
    # Migration: add updated_at column to user_assets
    try:
        conn.execute("ALTER TABLE user_assets ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    except sqlite3.OperationalError:
        pass
    # One-time migration: move holdings → user_assets type='mf'
    _migrate_holdings_to_assets(conn)
    _migrate_mf_declared_to_mf(conn)
    conn.commit()
    return conn


def _migrate_holdings_to_assets(conn: sqlite3.Connection):
    """Migrate holdings table rows into user_assets type='mf', source='verified'."""
    # Check if holdings table exists and has data
    try:
        count = conn.execute("SELECT COUNT(*) FROM holdings").fetchone()[0]
    except sqlite3.OperationalError:
        return  # No holdings table
    if count == 0:
        return
    # Check if we already migrated (any mf+verified rows exist)
    migrated = conn.execute(
        "SELECT COUNT(*) FROM user_assets WHERE asset_type = 'mf' AND source = 'verified'"
    ).fetchone()[0]
    if migrated > 0:
        return  # Already done
    rows = conn.execute("SELECT user_id, data FROM holdings").fetchall()
    now = datetime.now(timezone.utc).isoformat()
    for user_id, data_json in rows:
        d = json.loads(data_json)
        # Reconcile: remove any declared MF that fuzzy-matches this verified holding
        scheme = d.get("scheme_name", "")
        if scheme and user_id is not None:
            declared = conn.execute(
                "SELECT id, data FROM user_assets WHERE user_id = ? AND asset_type IN ('mf_declared', 'mf_sips')",
                (user_id,),
            ).fetchall()
            for did, ddata_json in declared:
                dd = json.loads(ddata_json)
                if _scheme_match(scheme, dd.get("scheme", "")):
                    conn.execute("DELETE FROM user_assets WHERE id = ?", (did,))
                    log.info(f"[migration] removed declared MF '{dd.get('scheme')}' — superseded by CAS '{scheme}'")
        conn.execute(
            "INSERT INTO user_assets (user_id, asset_type, data, source, source_detail, verified_at) VALUES (?, 'mf', ?, 'verified', 'cas_upload', ?)",
            (user_id, data_json, now),
        )
    log.info(f"[migration] migrated {len(rows)} holdings → user_assets type='mf'")


def _migrate_mf_declared_to_mf(conn: sqlite3.Connection):
    """Migrate mf_declared/mf_sips → asset_type='mf', source='declared'."""
    rows = conn.execute(
        "SELECT id FROM user_assets WHERE asset_type IN ('mf_declared', 'mf_sips') LIMIT 1"
    ).fetchall()
    if not rows:
        return
    conn.execute(
        "UPDATE user_assets SET asset_type = 'mf', source = 'declared' "
        "WHERE asset_type IN ('mf_declared', 'mf_sips')"
    )
    log.info(f"[migration] converted mf_declared/mf_sips → mf source='declared'")


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


# --- Unified Asset Layer ---


def _scheme_match(verified_name: str, declared_name: str) -> bool:
    """Fuzzy-match scheme names. Handles 'Parag Parikh Flexi Cap' vs full CAS name."""
    if not verified_name or not declared_name:
        return False
    v = verified_name.lower().split(" - ")[0].strip()
    d = declared_name.lower().split(" - ")[0].strip()
    # Exact prefix match or high similarity
    if v.startswith(d) or d.startswith(v):
        return True
    return SequenceMatcher(None, v, d).ratio() > 0.75


def _holding_to_asset_data(h: MFHolding) -> str:
    """Convert MFHolding to JSON string for user_assets storage."""
    data = asdict(h)
    for t in data.get("transactions", []):
        if hasattr(t.get("date"), "isoformat"):
            t["date"] = t["date"].isoformat()
    return json.dumps(data)


def _asset_to_holding(d: dict) -> MFHolding:
    """Convert user_assets dict → MFHolding. Handles both verified (full) and declared (partial)."""
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
    return MFHolding(
        scheme_name=d.get("scheme_name") or d.get("scheme", ""),
        folio=d.get("folio", ""),
        amc=d.get("amc", ""),
        isin=d.get("isin", ""),
        amfi_code=d.get("amfi_code", ""),
        plan=d.get("plan", ""),
        rta=d.get("rta", ""),
        units=float(d.get("units") or 0),
        nav=float(d.get("nav") or 0),
        current_value=float(d.get("current_value") or 0),
        invested_value=float(d.get("invested_value") or 0),
        expense_ratio=float(d.get("expense_ratio") or 0),
        annual_expense=float(d.get("annual_expense") or 0),
        category=d.get("category", ""),
        nav_date=d.get("nav_date", ""),
        day_change=float(d.get("day_change", 0)),
        day_change_pct=float(d.get("day_change_pct", 0)),
        morningstar=int(d.get("morningstar", 0)),
        aum=float(d.get("aum", 0)),
        risk_label=d.get("risk_label", ""),
        xirr=float(d.get("xirr", 0)),
        tax_section=d.get("tax_section", ""),
        transactions=txns,
    )


def reconcile_and_save(user_id: int, asset_type: str, verified_items: list,
                       source_detail: str = "cas_upload") -> dict:
    """Save verified assets, reconciling against existing declared entries.

    For MF: verified_items is list[MFHolding].
    For other types: verified_items is list[dict].

    Returns {"saved": N, "replaced": N, "new": N}.
    """
    conn = _get_conn()
    now = datetime.now(timezone.utc).isoformat()
    replaced, new = 0, 0

    # Load existing declared entries for this asset type
    declared_rows = conn.execute(
        "SELECT id, data FROM user_assets WHERE user_id = ? AND asset_type = ? AND source = 'declared'",
        (user_id, asset_type),
    ).fetchall()

    declared = [(rid, json.loads(rdata)) for rid, rdata in declared_rows]
    matched_ids = set()

    # Delete existing verified entries for this type (full replace on re-upload)
    conn.execute(
        "DELETE FROM user_assets WHERE user_id = ? AND asset_type = ? AND source = 'verified'",
        (user_id, asset_type),
    )

    for item in verified_items:
        if isinstance(item, MFHolding):
            data_json = _holding_to_asset_data(item)
            match_name = item.scheme_name
        else:
            data_json = json.dumps(item)
            match_name = item.get("scheme_name", item.get("scheme", ""))

        # Find matching declared entry
        for did, dd in declared:
            if did in matched_ids:
                continue
            d_name = dd.get("scheme_name") or dd.get("scheme", "")
            if asset_type == "mf" and _scheme_match(match_name, d_name):
                matched_ids.add(did)
                replaced += 1
                break
        else:
            new += 1

        conn.execute(
            "INSERT INTO user_assets (user_id, asset_type, data, source, source_detail, verified_at) "
            "VALUES (?, ?, ?, 'verified', ?, ?)",
            (user_id, asset_type, data_json, source_detail, now),
        )

    # Remove matched declared entries (superseded by verified)
    for did in matched_ids:
        conn.execute("DELETE FROM user_assets WHERE id = ?", (did,))

    conn.commit()
    conn.close()
    total = len(verified_items)
    log.info(f"[reconcile] {asset_type}: saved {total} verified ({replaced} replaced declared, {new} new)")
    return {"saved": total, "replaced": replaced, "new": new}


def load_mf_assets(user_id: int) -> list[MFHolding]:
    """Load all MF assets (verified + declared) as MFHolding objects.

    Single read path for all MF consumers: agent, holdings API, overview, goals.
    """
    conn = _get_conn()
    rows = conn.execute(
        "SELECT data, source FROM user_assets WHERE user_id = ? AND asset_type = 'mf'",
        (user_id,),
    ).fetchall()
    conn.close()

    holdings = []
    for data_json, source in rows:
        d = json.loads(data_json)
        d["_source"] = source
        h = _asset_to_holding(d)
        if h.current_value > 0 or h.units > 0 or (h.scheme_name and source == "declared"):
            holdings.append(h)
    return holdings


def clear_mf_assets(user_id: int):
    """Clear all MF assets (verified + declared) for a user."""
    conn = _get_conn()
    conn.execute(
        "DELETE FROM user_assets WHERE user_id = ? AND asset_type IN ('mf', 'mf_declared', 'mf_sips')",
        (user_id,),
    )
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
            "UPDATE goals SET name=?, template=?, target_amount=?, target_date=?, linked_folios=?, growth_rate=?, status=?, description=? WHERE id=? AND user_id=?",
            (goal.name, goal.template, goal.target_amount, goal.target_date, folios_json, goal.growth_rate, goal.status, goal.description, goal.id, goal.user_id),
        )
        conn.commit()
        conn.close()
        return goal.id
    cur = conn.execute(
        "INSERT INTO goals (user_id, name, template, target_amount, target_date, linked_folios, growth_rate, status, description) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (goal.user_id, goal.name, goal.template, goal.target_amount, goal.target_date, folios_json, goal.growth_rate, goal.status, goal.description),
    )
    conn.commit()
    gid = cur.lastrowid
    conn.close()
    return gid


def load_goals(user_id: int) -> list[Goal]:
    """Load all goals for a user."""
    conn = _get_conn()
    rows = conn.execute("SELECT id, user_id, name, template, target_amount, target_date, linked_folios, growth_rate, created_at, status, description FROM goals WHERE user_id=?", (user_id,)).fetchall()
    conn.close()
    return [
        Goal(id=r[0], user_id=r[1], name=r[2], template=r[3], target_amount=r[4], target_date=r[5],
             linked_folios=json.loads(r[6]) if r[6] else [], growth_rate=r[7], created_at=r[8] or "",
             status=r[9] or "active", description=r[10] or "")
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
    """Save profile by routing all fields through update_profile → user_assets."""
    from dataclasses import asdict
    data = {k: v for k, v in asdict(profile).items() if k != "user_id" and v}
    update_profile(profile.user_id, data)


def load_profile(user_id: int) -> UserProfile | None:
    """Load user profile reconstructed from user_assets (single storage)."""
    assets = load_assets(user_id)
    if not assets:
        # Fallback: try legacy user_profiles table for migration
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

    # Reconstruct from assets
    by_type = {}
    for a in assets:
        t = a.get("asset_type", "")
        by_type.setdefault(t, []).append(a)

    profile = UserProfile(user_id=user_id)

    # Helper to safely extract numeric values
    def num(d, key, default=0):
        v = d.get(key, default)
        if isinstance(v, str):
            v = v.replace(",", "").replace("₹", "").strip()
            try:
                return float(v) if v else default
            except ValueError:
                return default
        return float(v) if v else default

    # Personal section
    if "personal" in by_type:
        p = by_type["personal"][0]
        profile.name = p.get("name", "")
        profile.age = int(num(p, "age"))
        profile.occupation = p.get("occupation", "")
        profile.employer = p.get("employer", "")
        profile.location = p.get("location", "")
        profile.marital_status = p.get("marital_status", "")
        profile.kids = int(num(p, "kids"))
        profile.dependent_parents = p.get("dependent_parents", "")
        profile.parents_health_insurance = p.get("parents_health_insurance", "")
        profile.risk_tolerance = p.get("risk_tolerance", "")

    # Income section
    if "income" in by_type:
        inc = by_type["income"][0]
        profile.monthly_income = num(inc, "monthly_income")
        profile.annual_bonus = num(inc, "annual_bonus")
        profile.annual_rsu = num(inc, "annual_rsu")
        profile.monthly_sip = num(inc, "monthly_sip")
        profile.spouse_income = num(inc, "spouse_income")
        profile.other_income = num(inc, "other_income")

    # Expenses section
    if "expenses" in by_type:
        exp = by_type["expenses"][0]
        profile.total_monthly_expenses = num(exp, "total_monthly_expenses")
        profile.monthly_expenses = profile.total_monthly_expenses  # legacy alias
        profile.rent = num(exp, "rent")
        profile.groceries = num(exp, "groceries")
        profile.utilities = num(exp, "utilities")
        profile.dining = num(exp, "dining")
        profile.annual_big_ticket = num(exp, "annual_big_ticket")
        profile.emis = num(exp, "emis")

    # Insurance section
    if "insurance" in by_type:
        ins = by_type["insurance"][0]
        profile.term_cover = num(ins, "term_cover")
        profile.term_premium = num(ins, "term_premium")
        profile.health_cover = num(ins, "health_cover")
        profile.health_premium = num(ins, "health_premium")

    # Loan cards → loans list
    if "loan" in by_type:
        profile.loans = [{k: v for k, v in l.items() if k not in ("id", "asset_type")} for l in by_type["loan"]]

    # Meta section (onboarding_complete flag)
    if "meta" in by_type:
        m = by_type["meta"][0]
        profile.onboarding_complete = bool(m.get("onboarding_complete", False))

    return profile


def update_profile(user_id: int, updates: dict) -> UserProfile | None:
    """Partial update — route fields to correct asset_type sections."""
    SECTION_MAP = {
        "personal": {"name", "age", "occupation", "employer", "location", "marital_status", "kids",
                      "dependent_parents", "parents_health_insurance", "risk_tolerance", "dependents"},
        "income": {"monthly_income", "annual_bonus", "annual_rsu", "spouse_income", "other_income", "monthly_sip"},
        "expenses": {"total_monthly_expenses", "monthly_expenses", "rent", "groceries", "utilities",
                      "dining", "annual_big_ticket", "emis"},
        "insurance": {"term_cover", "term_premium", "health_cover", "health_premium", "health_employer_only"},
        "meta": {"onboarding_complete"},
    }
    # Group updates by section
    by_section = {}
    for key, val in updates.items():
        for section, fields in SECTION_MAP.items():
            if key in fields:
                by_section.setdefault(section, {})[key] = val
                break

    # Merge with existing data per section and save
    for section, new_data in by_section.items():
        existing = load_assets(user_id, section)
        merged = existing[0] if existing else {}
        # Strip asset metadata
        merged.pop("id", None)
        merged.pop("asset_type", None)
        merged.update(new_data)
        save_assets(user_id, section, [merged])

    return load_profile(user_id)


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


def clear_assets(user_id: int):
    """Clear all user assets."""
    conn = _get_conn()
    conn.execute("DELETE FROM user_assets WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def save_assets(user_id: int, asset_type: str, items: list[dict], source: str = None) -> int:
    import json
    conn = _get_conn()
    if source:
        conn.execute("DELETE FROM user_assets WHERE user_id = ? AND asset_type = ? AND source = ?",
                     (user_id, asset_type, source))
        for item in items:
            conn.execute("INSERT INTO user_assets (user_id, asset_type, data, source) VALUES (?, ?, ?, ?)",
                         (user_id, asset_type, json.dumps(item), source))
    else:
        conn.execute("DELETE FROM user_assets WHERE user_id = ? AND asset_type = ?",
                     (user_id, asset_type))
        for item in items:
            conn.execute("INSERT INTO user_assets (user_id, asset_type, data) VALUES (?, ?, ?)",
                         (user_id, asset_type, json.dumps(item)))
    conn.commit()
    conn.close()
    return len(items)


def load_assets(user_id: int, asset_type: str = None) -> list[dict]:
    import json
    conn = _get_conn()
    if asset_type:
        rows = conn.execute("SELECT id, asset_type, data, created_at FROM user_assets WHERE user_id = ? AND asset_type = ?",
                            (user_id, asset_type)).fetchall()
    else:
        rows = conn.execute("SELECT id, asset_type, data, created_at FROM user_assets WHERE user_id = ?",
                            (user_id,)).fetchall()
    conn.close()
    return [{"id": r[0], "asset_type": r[1], **json.loads(r[2]), "updated_at": r[3]} for r in rows]
