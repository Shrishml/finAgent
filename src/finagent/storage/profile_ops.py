"""User profile operations."""
from dataclasses import asdict, fields as dc_fields, MISSING

from sqlalchemy import select, delete

from finagent.storage.database import get_db
from finagent.storage.models import UserProfile as UserProfileModel
from finagent.storage.asset_ops import load_assets, save_assets
from finagent.models.profile import UserProfile


async def save_profile(profile: UserProfile):
    """Save profile by routing all fields through update_profile → user_assets."""
    data = {k: v for k, v in asdict(profile).items() if k != "user_id" and v}
    await update_profile(profile.user_id, data)


async def load_profile(user_id: int) -> UserProfile | None:
    """Load user profile reconstructed from user_assets (single storage)."""
    assets = await load_assets(user_id)
    if not assets:
        # Fallback: try legacy user_profiles table for migration
        async with get_db() as db:
            result = await db.execute(
                select(UserProfileModel).where(UserProfileModel.user_id == user_id)
            )
            row = result.scalar_one_or_none()
            if not row:
                return None
            d = row.data or {}
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
        profile.total_monthly_expenses = num(exp, "total_monthly_expenses") or num(exp, "monthly_expenses")
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


async def update_profile(user_id: int, updates: dict) -> UserProfile | None:
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
        existing = await load_assets(user_id, section)
        merged = existing[0] if existing else {}
        # Strip asset metadata
        merged.pop("id", None)
        merged.pop("asset_type", None)
        merged.update(new_data)
        await save_assets(user_id, section, [merged])

    return await load_profile(user_id)


async def clear_profile(user_id: int):
    """Clear user profile (legacy table)."""
    async with get_db() as db:
        await db.execute(delete(UserProfileModel).where(UserProfileModel.user_id == user_id))
