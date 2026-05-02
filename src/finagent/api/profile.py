"""Profile routes."""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from finagent.storage import load_profile, update_profile, load_mf_assets, get_latest_snapshot, save_assets, load_assets
from finagent.api.deps import get_user_id, require_auth, DEMO_USER_ID

log = logging.getLogger("finagent")
router = APIRouter(tags=["profile"])


@router.get("/profile")
async def get_profile(request: Request):
    user_id = await get_user_id(request) or DEMO_USER_ID
    profile = await load_profile(user_id)
    if not profile:
        return JSONResponse({"profile": None, "onboarding_complete": False})

    flags = []
    if profile.monthly_income > 0 and profile.savings_rate is not None:
        sr = profile.savings_rate
        if sr >= 0.3:
            flags.append(("✅", f"Savings rate {sr:.0%} — excellent!"))
        elif sr >= 0.2:
            flags.append(("🟡", f"Savings rate {sr:.0%} — aim for 30%+"))
        else:
            flags.append(("🔴", f"Savings rate {sr:.0%} — needs improvement"))
    if profile.term_cover > 0:
        flags.append(("✅", f"Term cover ₹{profile.term_cover/100000:.0f}L"))
    if not profile.loans or profile.total_emi == 0:
        flags.append(("✅", "Debt free!"))
    elif profile.monthly_income > 0:
        dti = profile.total_emi / profile.monthly_income
        if dti < 0.3:
            flags.append(("✅", f"Debt-to-income {dti:.0%} — manageable"))
        else:
            flags.append(("🟡", f"Debt-to-income {dti:.0%} — consider reducing"))

    return JSONResponse({
        "profile": {
            "name": profile.name, "age": profile.age,
            "monthly_income": profile.monthly_income,
            "monthly_expenses": profile.total_monthly_expenses or profile.monthly_expenses,
            "savings_rate": profile.savings_rate, "occupation": profile.occupation,
            "employer": profile.employer, "dependents": profile.dependents,
            "location": profile.location, "marital_status": profile.marital_status, "kids": profile.kids,
            "risk_tolerance": profile.risk_tolerance, "loans": profile.loans, "total_emi": profile.total_emi,
            "term_cover": profile.term_cover, "health_cover": profile.health_cover,
            "onboarding_complete": profile.onboarding_complete,
            "goals_mentioned": profile.goals_mentioned,
        },
        "flags": flags,
        "onboarding_complete": profile.onboarding_complete,
        "financial_snapshot": profile.financial_snapshot or None,
    })


@router.put("/profile")
async def save_profile_endpoint(request: Request):
    user_id = await get_user_id(request) or DEMO_USER_ID
    body = await request.json()
    allowed = {
        "name", "age", "occupation", "employer", "location", "marital_status", "kids",
        "dependent_parents", "parents_health_insurance", "risk_tolerance", "dependents",
        "monthly_income", "annual_bonus", "spouse_income", "other_income",
        "total_monthly_expenses", "monthly_expenses", "rent", "groceries", "utilities",
        "dining", "annual_big_ticket", "emis",
        "term_cover", "term_premium", "health_cover", "health_premium",
        "onboarding_complete",
    }
    updates = {k: v for k, v in body.items() if k in allowed}
    profile = await update_profile(user_id, updates)
    return JSONResponse({"status": "ok", "onboarding_complete": profile.onboarding_complete})


@router.get("/snapshot")
async def get_snapshot(request: Request):
    user_id = await get_user_id(request) or DEMO_USER_ID
    snap = await get_latest_snapshot(user_id)
    if not snap:
        return JSONResponse({"snapshot": None})
    return JSONResponse(snap)


VALID_ASSET_TYPES = {"fd", "realestate", "gold", "esop", "loan",
                     "personal", "income", "expenses", "epf_ppf", "nps",
                     "stocks", "insurance", "tax", "meta"}


@router.post("/profile/assets")
async def save_profile_assets(request: Request):
    user_id = await get_user_id(request) or DEMO_USER_ID
    body = await request.json()
    asset_type = body.get("asset_type", "")
    items = body.get("items", [])
    if asset_type not in VALID_ASSET_TYPES:
        return JSONResponse({"ok": False, "error": f"Invalid asset type: {asset_type}"}, status_code=400)
    if not items:
        return JSONResponse({"ok": False, "error": "No items provided"}, status_code=400)
    count = await save_assets(user_id, asset_type, items)
    log.info(f"[profile] Saved {count} {asset_type} assets for user {user_id}")
    return JSONResponse({"ok": True, "count": count})


@router.get("/profile/assets")
async def get_profile_assets(request: Request):
    user_id = await get_user_id(request) or DEMO_USER_ID
    asset_type = request.query_params.get("type")
    items = await load_assets(user_id, asset_type)
    # Migrate legacy field names
    _RENAMES = {"epf_monthly": "epf_contribution", "nps_monthly": "nps_contribution"}
    for item in items:
        for old, new in _RENAMES.items():
            if old in item and new not in item:
                item[new] = item.pop(old)
    return JSONResponse({"items": items})
