"""Overview dashboard API — aggregates net worth, goals, cash flow, nudges, activity."""
import json
import logging
from datetime import date, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from finagent.api.deps import get_user_id, DEMO_USER_ID
from finagent.api.goals import _compute_goal_progress, _asset_value, ASSET_VALUE_FIELDS
from finagent.models.goal import Goal
from finagent.models.profile import UserProfile
from finagent.storage.sqlite import (
    load_holdings, load_goals, load_assets, load_profile, load_conversation, _get_conn,
)

log = logging.getLogger(__name__)
router = APIRouter()

# ── Asset type labels ──
_ASSET_LABELS = {
    "epf_ppf": "EPF & PPF", "fd": "Fixed Deposits", "gold": "Gold",
    "esop": "ESOP/RSU", "realestate": "Real Estate", "nps": "NPS",
    "mf_declared": "Mutual Funds (declared)", "mf_sips": "SIPs (declared)",
}


def _net_worth(user_id: int, holdings: list) -> dict:
    """Compute total net worth across all asset classes."""
    mf_value = sum(h.current_value for h in holdings)
    mf_invested = sum(getattr(h, 'invested', 0) or 0 for h in holdings)

    assets = load_assets(user_id)
    asset_breakdown = {}
    for a in assets:
        at = a.get("asset_type", "")
        val = _asset_value(a)
        if val > 0:
            label = _ASSET_LABELS.get(at, at)
            asset_breakdown[label] = asset_breakdown.get(label, 0) + val

    if mf_value > 0:
        asset_breakdown["Mutual Funds (CAS)"] = mf_value

    total = sum(asset_breakdown.values())
    return {
        "total": round(total, 2),
        "mf_value": round(mf_value, 2),
        "mf_invested": round(mf_invested, 2),
        "mf_gain": round(mf_value - mf_invested, 2),
        "breakdown": {k: round(v, 2) for k, v in sorted(asset_breakdown.items(), key=lambda x: -x[1])},
    }


def _goal_summaries(user_id: int, holdings: list) -> list:
    """Top 3 goals with progress."""
    goals = load_goals(user_id)
    active = [g for g in goals if g.status == "active"]
    result = []
    for g in active[:3]:
        prog = _compute_goal_progress(g, holdings, user_id)
        result.append({
            "id": g.id, "name": g.name, "template": g.template,
            "target_amount": g.target_amount, "target_date": g.target_date,
            "current_value": prog["current_value"],
            "progress_pct": prog["progress_pct"],
            "on_track": prog["on_track"],
            "months_left": prog["months_left"],
        })
    return result


def _cash_flow(profile: UserProfile | None) -> dict | None:
    """Monthly cash flow from profile data."""
    if not profile or not profile.monthly_income:
        return None
    income = profile.monthly_income or 0
    expenses = profile.total_monthly_expenses or profile.monthly_expenses or 0
    emi = profile.total_emi or 0
    investments = profile.monthly_sip or 0
    surplus = income - expenses - emi - investments
    return {
        "income": round(income), "expenses": round(expenses),
        "emi": round(emi), "investments": round(investments),
        "surplus": round(surplus),
    }


def _nudges(user_id: int, profile: UserProfile | None, goals: list, holdings: list, net_worth: dict) -> list:
    """Generate 2-4 smart, contextual action items."""
    nudges = []

    # Emergency fund check
    if profile and profile.total_monthly_expenses:
        ef_goals = [g for g in goals if g.template == "emergency"]
        if not ef_goals:
            months_exp = profile.total_monthly_expenses
            nudges.append({
                "icon": "🛡️", "title": "No emergency fund goal",
                "desc": f"Aim for 6 months of expenses (₹{months_exp * 6:,.0f})",
                "action": "Set up emergency fund", "tab": "goals",
            })
        else:
            for g in ef_goals:
                prog = _compute_goal_progress(g, holdings, user_id)
                if prog["progress_pct"] < 100:
                    months_covered = prog["current_value"] / profile.total_monthly_expenses if profile.total_monthly_expenses else 0
                    nudges.append({
                        "icon": "🛡️", "title": f"Emergency fund: {months_covered:.0f} months covered",
                        "desc": f"Target is 6 months — {prog['progress_pct']:.0f}% there",
                        "action": "View goal", "tab": "goals",
                    })

    # Surplus sitting idle
    if profile and profile.monthly_income:
        income = profile.monthly_income
        expenses = (profile.total_monthly_expenses or 0) + (profile.total_emi or 0) + (profile.monthly_sip or 0)
        surplus = income - expenses
        if surplus > 5000:
            nudges.append({
                "icon": "💰", "title": f"₹{surplus:,.0f}/month surplus is unallocated",
                "desc": "Consider investing this or linking to a goal",
                "action": "Ask Arth", "chat": f"I have ₹{surplus:,.0f} surplus monthly. What should I do with it?",
            })

    # Stale data check
    assets = load_assets(user_id)
    if assets:
        from finagent.freshness import get_confidence, freshness_label
        stale = []
        for a in assets:
            conf = get_confidence(a.get("asset_type", ""), a.get("updated_at"))
            if freshness_label(conf) == "stale":
                label = _ASSET_LABELS.get(a.get("asset_type", ""), a.get("asset_type", ""))
                stale.append(label)
        if stale:
            unique = list(dict.fromkeys(stale))[:3]
            nudges.append({
                "icon": "📅", "title": f"{', '.join(unique)} data may be outdated",
                "desc": "Update for more accurate advice",
                "action": "Update profile", "tab": "profile",
            })

    # No goals at all
    if not goals:
        nudges.append({
            "icon": "🎯", "title": "No financial goals set",
            "desc": "Goals help you track progress and stay motivated",
            "action": "Create a goal", "tab": "goals",
        })

    # No holdings
    if not holdings:
        nudges.append({
            "icon": "📄", "title": "Upload your CAS statement",
            "desc": "See your exact mutual fund portfolio with returns & XIRR",
            "action": "Upload CAS", "modal": "upload-modal",
        })

    # Insurance gaps
    if profile:
        if not profile.term_cover and profile.monthly_income and profile.monthly_income > 30000:
            nudges.append({
                "icon": "⚠️", "title": "No term life insurance",
                "desc": "A term plan is the most cost-effective way to protect your family",
                "action": "Ask Arth", "chat": "Do I need term life insurance?",
            })
        if not profile.health_cover:
            nudges.append({
                "icon": "🏥", "title": "No personal health insurance",
                "desc": "Don't rely solely on employer coverage",
                "action": "Ask Arth", "chat": "Should I get personal health insurance?",
            })

    return nudges[:4]


def _recent_activity(user_id: int) -> list:
    """Last 4 meaningful activities from conversation metadata."""
    conn = _get_conn()
    rows = conn.execute(
        """SELECT content, metadata, created_at FROM conversations
           WHERE user_id = ? AND role = 'assistant' AND metadata != '{}'
           ORDER BY created_at DESC LIMIT 20""",
        (user_id,),
    ).fetchall()
    conn.close()

    activities = []
    seen = set()
    for content, meta_str, ts in rows:
        meta = json.loads(meta_str) if meta_str else {}
        actions = meta.get("actions", [])
        for act in actions:
            action_type = act.get("action", "")
            summary = None
            if action_type == "create_goal":
                summary = f"Created goal: {act.get('name', 'Unknown')}"
            elif action_type == "collect_profile_data":
                fields = list(act.get("data", {}).keys())[:3]
                if fields:
                    summary = f"Updated profile: {', '.join(fields)}"
            elif action_type == "link_asset_to_goal":
                summary = f"Linked asset to {act.get('goal_name', 'a goal')}"
            elif action_type == "save_asset":
                summary = f"Added {_ASSET_LABELS.get(act.get('asset_type', ''), act.get('asset_type', ''))}"

            if summary and summary not in seen:
                seen.add(summary)
                activities.append({"summary": summary, "timestamp": ts})
                if len(activities) >= 4:
                    break
        if len(activities) >= 4:
            break

    return activities


@router.get("/overview")
async def overview(request: Request):
    """Aggregated overview dashboard data."""
    user_id = get_user_id(request) or DEMO_USER_ID
    holdings = load_holdings(user_id)
    profile = load_profile(user_id)
    goals = load_goals(user_id)

    nw = _net_worth(user_id, holdings)
    goal_cards = _goal_summaries(user_id, holdings)
    cash = _cash_flow(profile)
    nudge_list = _nudges(user_id, profile, goals, holdings, nw)
    activity = _recent_activity(user_id)

    return JSONResponse({
        "net_worth": nw,
        "goals": goal_cards,
        "cash_flow": cash,
        "nudges": nudge_list,
        "activity": activity,
        "has_holdings": len(holdings) > 0,
        "has_profile": profile is not None and profile.onboarding_complete,
        "user_name": profile.name if profile else None,
    })
