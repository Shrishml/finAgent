"""Profile routes — health score, flags, action items."""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from finagent.storage.sqlite import load_profile, update_profile, load_holdings
from finagent.api.deps import get_user_id, require_auth, DEMO_USER_ID

log = logging.getLogger("finagent")
router = APIRouter(tags=["profile"])


def _build_action_items(profile, user_id):
    items = []
    holdings = load_holdings(user_id)
    if not holdings:
        items.append({"icon": "📄", "text": "Upload a CAMS/KFintech CAS statement to track your mutual funds", "priority": 1})
    if profile.term_cover == 0 and "insurance" in profile.pillars_completed:
        items.append({"icon": "🛡️", "text": "Get a term life insurance policy — top priority with dependents", "priority": 1})
    if profile.health_employer_only and "insurance" in profile.pillars_completed:
        items.append({"icon": "🏥", "text": "Consider a personal health insurance policy beyond employer cover", "priority": 2})
    for g in profile.goals_mentioned:
        items.append({"icon": "🎯", "text": f"Set up goal: {g}", "priority": 2, "action": "goals"})
    if profile.pillars_skipped:
        for p in profile.pillars_skipped:
            items.append({"icon": "⏭️", "text": f"Complete skipped section: {p}", "priority": 3})
    return sorted(items, key=lambda x: x.get("priority", 9))


@router.get("/profile")
async def get_profile(request: Request):
    user_id = get_user_id(request) or DEMO_USER_ID
    profile = load_profile(user_id)
    if not profile:
        return JSONResponse({"profile": None, "onboarding_complete": False})

    score = 0
    flags = []
    if profile.monthly_income > 0:
        score += 15
    if profile.monthly_expenses > 0:
        score += 10
        if profile.savings_rate and profile.savings_rate >= 0.3:
            score += 10
            flags.append(("✅", f"Savings rate {profile.savings_rate:.0%} — excellent!"))
        elif profile.savings_rate and profile.savings_rate >= 0.2:
            score += 5
            flags.append(("🟡", f"Savings rate {profile.savings_rate:.0%} — aim for 30%+"))
        elif profile.savings_rate is not None:
            flags.append(("🔴", f"Savings rate {profile.savings_rate:.0%} — needs improvement"))
    if profile.term_cover > 0:
        score += 15
        flags.append(("✅", f"Term cover ₹{profile.term_cover/100000:.0f}L"))
    elif "insurance" in profile.pillars_completed:
        flags.append(("🔴", "No term life insurance — top priority!"))
    if profile.health_cover > 0 or not profile.health_employer_only:
        score += 10
    elif "insurance" in profile.pillars_completed:
        score += 5
        flags.append(("🟡", "Only employer health cover — consider personal policy"))
    if not profile.loans or profile.total_emi == 0:
        score += 15
        flags.append(("✅", "Debt free!"))
    elif profile.monthly_income > 0:
        dti = profile.total_emi / profile.monthly_income
        if dti < 0.3:
            score += 10
            flags.append(("✅", f"Debt-to-income {dti:.0%} — manageable"))
        else:
            score += 5
            flags.append(("🟡", f"Debt-to-income {dti:.0%} — consider reducing"))
    if profile.age > 0:
        score += 5
    if profile.risk_tolerance:
        score += 5
    if len(profile.pillars_completed) >= 6:
        score += 10

    return JSONResponse({
        "profile": {
            "monthly_income": profile.monthly_income, "monthly_expenses": profile.monthly_expenses,
            "savings_rate": profile.savings_rate, "occupation": profile.occupation,
            "employer": profile.employer, "age": profile.age, "dependents": profile.dependents,
            "location": profile.location, "marital_status": profile.marital_status, "kids": profile.kids,
            "risk_tolerance": profile.risk_tolerance, "loans": profile.loans, "total_emi": profile.total_emi,
            "term_cover": profile.term_cover, "health_cover": profile.health_cover,
            "health_employer_only": profile.health_employer_only,
            "pillars_completed": profile.pillars_completed, "pillars_skipped": profile.pillars_skipped,
            "onboarding_complete": profile.onboarding_complete, "goals_mentioned": profile.goals_mentioned,
        },
        "health_score": min(score, 100), "flags": flags,
        "action_items": _build_action_items(profile, user_id),
        "onboarding_complete": profile.onboarding_complete,
        "financial_snapshot": profile.financial_snapshot or None,
    })


@router.put("/profile")
async def save_profile_endpoint(request: Request, user_id: int = Depends(require_auth)):
    body = await request.json()
    allowed = {
        "monthly_income", "annual_bonus", "spouse_income", "other_income",
        "monthly_expenses", "rent", "emis", "loans", "total_investments",
        "term_cover", "health_cover", "health_employer_only",
        "age", "dependents", "occupation", "employer", "risk_tolerance",
        "location", "marital_status", "kids",
        "goals_mentioned", "pillars_completed", "onboarding_complete",
    }
    updates = {k: v for k, v in body.items() if k in allowed}
    profile = update_profile(user_id, updates)
    return JSONResponse({"status": "ok", "onboarding_complete": profile.onboarding_complete})
