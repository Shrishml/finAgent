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
    "loan": "Loans", "stocks": "Stocks",
}


def _net_worth(user_id: int, holdings: list) -> dict:
    """Compute total net worth across all asset classes."""
    mf_value = sum(h.current_value for h in holdings)
    mf_invested = sum(getattr(h, 'invested', 0) or 0 for h in holdings)

    assets = load_assets(user_id)
    asset_items = {}
    liabilities = {}
    # Allocation buckets
    alloc = {"Equity": 0, "Debt": 0, "Gold": 0, "Real Estate": 0, "Cash": 0}

    for a in assets:
        at = a.get("asset_type", "")
        val = _asset_value(a)
        if val <= 0:
            continue
        label = _ASSET_LABELS.get(at, at)
        # Loans are liabilities
        if at == "loan":
            liabilities[label] = liabilities.get(label, 0) + val
            continue
        asset_items[label] = asset_items.get(label, 0) + val
        # Map to allocation buckets
        if at in ("esop", "mf_declared", "mf_sips", "stocks"):
            alloc["Equity"] += val
        elif at in ("fd", "epf_ppf", "nps"):
            alloc["Debt"] += val
        elif at == "gold":
            alloc["Gold"] += val
        elif at == "realestate":
            alloc["Real Estate"] += val
        else:
            alloc["Cash"] += val

    if mf_value > 0:
        asset_items["Mutual Funds (CAS)"] = mf_value
        alloc["Equity"] += mf_value

    total_assets = sum(asset_items.values())
    total_liabilities = sum(liabilities.values())
    total = total_assets - total_liabilities

    return {
        "total": round(total, 2),
        "total_assets": round(total_assets, 2),
        "total_liabilities": round(total_liabilities, 2),
        "mf_value": round(mf_value, 2),
        "mf_invested": round(mf_invested, 2),
        "mf_gain": round(mf_value - mf_invested, 2),
        "assets": {k: round(v, 2) for k, v in sorted(asset_items.items(), key=lambda x: -x[1])},
        "liabilities": {k: round(v, 2) for k, v in sorted(liabilities.items(), key=lambda x: -x[1])},
        "allocation": {k: round(v, 2) for k, v in alloc.items() if v > 0},
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


def _context_actions(net_worth: dict, goals: list, cash_flow: dict | None, profile: UserProfile | None) -> dict:
    """Generate section-specific contextual action prompts for chat."""
    actions = {}

    # After net worth
    nw_actions = []
    alloc = net_worth.get("allocation", {})
    ideal = net_worth.get("ideal_allocation", {})
    total_alloc = sum(alloc.values())
    if total_alloc > 0 and ideal:
        biggest_gap = max(ideal, key=lambda k: abs((alloc.get(k, 0) / total_alloc * 100) - ideal.get(k, 0)))
        cur = alloc.get(biggest_gap, 0) / total_alloc * 100
        tgt = ideal.get(biggest_gap, 0)
        if abs(cur - tgt) >= 5:
            nw_actions.append(f"My {biggest_gap} allocation is {cur:.0f}% vs {tgt}% suggested. How do I rebalance?")
    if net_worth.get("total_liabilities", 0) > 0:
        nw_actions.append("Should I prioritize paying off debt or investing more?")
    if not nw_actions:
        nw_actions.append("How does my net worth compare for my age group?")
    actions["net_worth"] = nw_actions[:2]

    # After goals
    g_actions = []
    behind = [g for g in goals if not g.get("on_track")]
    if behind:
        g_actions.append(f"My {behind[0]['name']} goal is behind. How do I catch up?")
    if len(goals) < 3:
        g_actions.append("What financial goals should someone my age have?")
    if any(g.get("template") == "retirement" for g in goals):
        g_actions.append("Am I saving enough for retirement?")
    actions["goals"] = g_actions[:2]

    # After cash flow
    cf_actions = []
    if cash_flow:
        if cash_flow.get("surplus", 0) > 5000:
            cf_actions.append(f"I have ₹{cash_flow['surplus']:,} surplus. Where should it go?")
        if cash_flow.get("emi", 0) > 0 and cash_flow.get("income", 0) > 0:
            emi_pct = cash_flow["emi"] / cash_flow["income"] * 100
            if emi_pct > 20:
                cf_actions.append(f"My EMIs are {emi_pct:.0f}% of income. Is that too high?")
        if not cf_actions:
            cf_actions.append("How can I optimize my monthly cash flow?")
    actions["cash_flow"] = cf_actions[:2]

    return actions


@router.get("/overview/demo")
async def overview_demo():
    """Demo overview with rich dummy data for showcasing the UI."""
    return JSONResponse({
        "net_worth": {
            "total": 4482500,
            "total_assets": 4832500,
            "total_liabilities": 350000,
            "mf_value": 2150000,
            "mf_invested": 1680000,
            "mf_gain": 470000,
            "assets": {
                "Mutual Funds": 2150000,
                "EPF & PPF": 1120000,
                "Fixed Deposits": 500000,
                "Gold (SGB + Physical)": 380000,
                "NPS": 350000,
                "ESOP/RSU": 332500,
            },
            "liabilities": {
                "Car Loan": 280000,
                "Credit Card": 70000,
            },
            "allocation": {
                "Equity": 2482500,
                "Debt": 1620000,
                "Gold": 380000,
                "Real Estate": 0,
                "Cash": 350000,
            },
            "ideal_allocation": {
                "Equity": 65,
                "Debt": 20,
                "Gold": 10,
                "Real Estate": 0,
                "Cash": 5,
            },
        },
        "goals": [
            {"id": 1, "name": "Retirement at 50", "template": "retirement",
             "target_amount": 65000000, "target_date": "2051-01-01",
             "current_value": 3270000, "progress_pct": 5, "on_track": True, "months_left": 300},
            {"id": 2, "name": "Dream Home", "template": "house",
             "target_amount": 12000000, "target_date": "2031-06-01",
             "current_value": 2800000, "progress_pct": 23, "on_track": False, "months_left": 62},
            {"id": 3, "name": "Emergency Fund", "template": "emergency",
             "target_amount": 360000, "target_date": "2027-01-01",
             "current_value": 280000, "progress_pct": 78, "on_track": True, "months_left": 8},
        ],
        "cash_flow": {
            "income": 185000, "expenses": 55000,
            "emi": 22000, "investments": 65000, "surplus": 43000,
        },
        "nudges": [
            {"icon": "💰", "title": "₹43,000/month surplus is unallocated",
             "desc": "Consider increasing SIP or linking to your house goal",
             "action": "Ask Arth", "chat": "I have ₹43,000 surplus monthly. What should I do with it?"},
            {"icon": "🛡️", "title": "Emergency fund: 5 months covered",
             "desc": "Target is 6 months — 78% there. ₹80K more to go",
             "action": "View goal", "tab": "goals"},
            {"icon": "⚠️", "title": "No term life insurance",
             "desc": "At ₹1.85L/month income, a ₹2Cr term plan costs ~₹800/month",
             "action": "Ask Arth", "chat": "Do I need term life insurance? What cover amount?"},
            {"icon": "📅", "title": "EPF data is 3 months old",
             "desc": "Update for more accurate net worth tracking",
             "action": "Update profile", "tab": "profile"},
        ],
        "has_holdings": True,
        "has_profile": True,
        "user_name": "Suraj",
        "context_actions": {
            "net_worth": [
                "My Equity allocation is 51% vs 65% suggested. How do I rebalance?",
                "Should I prioritize paying off debt or investing more?",
            ],
            "goals": [
                "My Dream Home goal is behind. How do I catch up?",
                "Am I saving enough for retirement?",
            ],
            "cash_flow": [
                "I have ₹43,000 surplus. Where should it go?",
                "My EMIs are 12% of income. Is that healthy?",
            ],
        },
    })


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

    ctx_actions = _context_actions(nw, goal_cards, cash, profile)

    return JSONResponse({
        "net_worth": nw,
        "goals": goal_cards,
        "cash_flow": cash,
        "nudges": nudge_list,
        "activity": activity,
        "context_actions": ctx_actions,
        "has_holdings": len(holdings) > 0,
        "has_profile": profile is not None and profile.onboarding_complete,
        "user_name": profile.name if profile else None,
    })
