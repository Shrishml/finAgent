"""Goals routes — CRUD, templates, allocations, progress projections."""
import logging
from datetime import date as _date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from finagent.models.goal import Goal, GOAL_TEMPLATES
from finagent.storage.sqlite import save_goal, load_goals, delete_goal, load_mf_assets, load_assets
from finagent.api.deps import get_user_id, require_auth, DEMO_USER_ID

log = logging.getLogger("finagent")
router = APIRouter(tags=["goals"])


ASSET_VALUE_FIELDS = {
    "fd": "amount", "gold": "value", "esop": "vested",
    "realestate": "current_value", "nps": "nps_balance",
    "loan": "outstanding",
    # Legacy — existing goal links may reference these types
    "mf_declared": "current_value", "mf_sips": "current_value",
}

def _asset_value(item: dict) -> float:
    """Extract monetary value from a user_asset item."""
    at = item.get("asset_type", "")
    if at == "epf_ppf":
        return float(item.get("epf_balance", 0) or 0) + float(item.get("ppf_balance", 0) or 0)
    field = ASSET_VALUE_FIELDS.get(at)
    return float(item.get(field, 0) or 0) if field else 0


def _compute_goal_progress(goal: Goal, holdings: list, user_id: int) -> dict:
    """Compute progress, monthly SIP, and projection for a goal."""
    linked_value = 0.0
    monthly_sip = 0.0
    alloc_map = {}
    asset_links = []
    for lf in goal.linked_folios:
        if isinstance(lf, dict) and "asset_type" in lf:
            asset_links.append(lf)
        elif isinstance(lf, dict):
            alloc_map[lf["folio"]] = lf.get("pct", 100) / 100
        else:
            alloc_map[lf] = 1.0

    # MF holdings
    for h in holdings:
        key = f"{h.folio}/{h.scheme_name}"
        if key not in alloc_map:
            continue
        weight = alloc_map[key]
        linked_value += h.current_value * weight
        cutoff = _date.today() - timedelta(days=180)
        recent_investments = sum(t.amount for t in h.transactions if t.amount > 0 and t.date >= cutoff)
        monthly_sip += (recent_investments / 6) * weight

    # Linked assets (FDs, gold, EPF/PPF, NPS, etc.)
    for al in asset_links:
        items = load_assets(user_id, al["asset_type"])
        match = next((i for i in items if i.get("id") == al.get("asset_id")), items[0] if items else None)
        if match:
            w = al.get("pct", 100) / 100
            linked_value += _asset_value(match) * w
            if al["asset_type"] in ("mf", "mf_declared", "mf_sips"):
                monthly_sip += float(match.get("monthly_sip", 0) or 0) * w

    progress_pct = (linked_value / goal.target_amount * 100) if goal.target_amount > 0 else 0
    if not goal.target_date:
        # No deadline (e.g. suggested emergency fund) — just show progress
        return {
            "current_value": round(linked_value, 2), "progress_pct": round(min(progress_pct, 100), 1),
            "monthly_sip": 0, "projected_value": round(linked_value, 2),
            "months_left": 0, "projected_months": None, "on_track": linked_value >= goal.target_amount,
            "sip_gap": 0,
        }
    td = goal.target_date if len(goal.target_date) > 7 else goal.target_date + "-01"
    target_dt = _date.fromisoformat(td)
    months_left = max(0, (target_dt.year - _date.today().year) * 12 + target_dt.month - _date.today().month)

    monthly_rate = goal.growth_rate / 12
    if monthly_rate > 0 and months_left > 0:
        fv_lump = linked_value * (1 + monthly_rate) ** months_left
        fv_sip = monthly_sip * (((1 + monthly_rate) ** months_left - 1) / monthly_rate)
        projected_value = fv_lump + fv_sip
    else:
        projected_value = linked_value + monthly_sip * months_left

    projected_months = None
    if monthly_rate > 0 and (linked_value > 0 or monthly_sip > 0):
        for m in range(1, 600):
            fv = linked_value * (1 + monthly_rate) ** m + monthly_sip * (((1 + monthly_rate) ** m - 1) / monthly_rate)
            if fv >= goal.target_amount:
                projected_months = m
                break

    on_track = projected_value >= goal.target_amount if months_left > 0 else linked_value >= goal.target_amount

    sip_gap = 0.0
    if not on_track and months_left > 0 and monthly_rate > 0:
        fv_lump = linked_value * (1 + monthly_rate) ** months_left
        annuity_factor = ((1 + monthly_rate) ** months_left - 1) / monthly_rate
        if annuity_factor > 0:
            required_sip = (goal.target_amount - fv_lump) / annuity_factor
            sip_gap = max(0, required_sip - monthly_sip)

    return {
        "current_value": round(linked_value, 2), "progress_pct": round(min(progress_pct, 100), 1),
        "monthly_sip": round(monthly_sip, 2), "projected_value": round(projected_value, 2),
        "months_left": months_left, "projected_months": projected_months,
        "on_track": on_track, "sip_gap": round(sip_gap, 2),
    }


def _validate_allocations(user_id: int, linked_folios: list, exclude_goal_id: int | None = None):
    existing_goals = load_goals(user_id)
    alloc = {}
    for g in existing_goals:
        if g.id == exclude_goal_id:
            continue
        for lf in g.linked_folios:
            if isinstance(lf, dict) and "asset_type" in lf:
                key = f"asset:{lf['asset_type']}:{lf.get('asset_id', 0)}"
                alloc[key] = alloc.get(key, 0) + lf.get("pct", 100)
            elif isinstance(lf, dict):
                alloc[lf["folio"]] = alloc.get(lf["folio"], 0) + lf.get("pct", 100)
            else:
                alloc[lf] = alloc.get(lf, 0) + 100
    for lf in linked_folios:
        if isinstance(lf, dict) and "asset_type" in lf:
            key = f"asset:{lf['asset_type']}:{lf.get('asset_id', 0)}"
            pct = lf.get("pct", 100)
        elif isinstance(lf, dict):
            key, pct = lf["folio"], lf.get("pct", 100)
        else:
            key, pct = lf, 100
        total = alloc.get(key, 0) + pct
        if total > 100:
            raise HTTPException(status_code=400, detail=f"'{key}' would be {total}% allocated (max 100%)")


LINKABLE_TYPES = {"fd", "gold", "esop", "epf_ppf", "nps", "realestate"}
ASSET_LABELS = {"fd": "Fixed Deposit", "gold": "Gold", "esop": "ESOP/RSU",
                "epf_ppf": "EPF/PPF", "nps": "NPS", "realestate": "Real Estate"}


@router.get("/goals/linkable-assets")
async def linkable_assets(request: Request):
    user_id = get_user_id(request) or DEMO_USER_ID
    result = []
    for at in LINKABLE_TYPES:
        items = load_assets(user_id, at)
        for item in items:
            val = _asset_value(item)
            if val <= 0:
                continue
            # Build a display name
            if at == "fd":
                label = f"FD — {item.get('bank', 'Unknown')}"
            elif at == "gold":
                label = f"Gold — {item.get('type', 'Physical')}"
            elif at == "esop":
                label = f"ESOP — {item.get('company', 'Unknown')}"
            elif at == "realestate":
                label = f"Property — {item.get('location', 'Unknown')}"
            else:
                label = ASSET_LABELS.get(at, at)
            result.append({"asset_type": at, "asset_id": item.get("id", 0),
                           "label": label, "value": val})
    return JSONResponse({"assets": result})


@router.get("/goals/templates")
async def goal_templates():
    return JSONResponse({"templates": {k: v for k, v in GOAL_TEMPLATES.items()}})


@router.get("/goals/allocations")
async def goal_allocations(request: Request):
    user_id = get_user_id(request) or DEMO_USER_ID
    exclude_id = request.query_params.get("exclude")
    exclude_id = int(exclude_id) if exclude_id else None
    goals = load_goals(user_id)
    alloc = {}
    for g in goals:
        if g.id == exclude_id:
            continue
        for lf in g.linked_folios:
            if isinstance(lf, dict) and "asset_type" in lf:
                key = f"asset:{lf['asset_type']}:{lf.get('asset_id', 0)}"
                alloc[key] = alloc.get(key, 0) + lf.get("pct", 100)
            elif isinstance(lf, dict):
                alloc[lf["folio"]] = alloc.get(lf["folio"], 0) + lf.get("pct", 100)
            else:
                alloc[lf] = alloc.get(lf, 0) + 100
    return JSONResponse({"allocations": alloc})


@router.get("/goals")
async def get_goals(request: Request):
    user_id = get_user_id(request) or DEMO_USER_ID
    goals = load_goals(user_id)
    holdings = load_mf_assets(user_id)
    return JSONResponse({
        "goals": [{
            "id": g.id, "name": g.name, "template": g.template,
            "target_amount": g.target_amount, "target_date": g.target_date,
            "linked_folios": g.linked_folios, "growth_rate": g.growth_rate,
            "created_at": g.created_at, "status": g.status,
            "description": g.description,
            **_compute_goal_progress(g, holdings, user_id),
        } for g in goals]
    })


@router.post("/goals")
async def create_goal(request: Request, user_id: int = Depends(require_auth)):
    body = await request.json()
    name = body.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Goal name required")
    template = body.get("template", "custom")
    if template not in GOAL_TEMPLATES:
        raise HTTPException(status_code=400, detail=f"Unknown template: {template}")
    target_amount = body.get("target_amount", 0)
    target_date = body.get("target_date", "")
    if not target_date or target_amount <= 0:
        raise HTTPException(status_code=400, detail="target_amount and target_date required")
    linked = body.get("linked_folios", [])
    _validate_allocations(user_id, linked)
    goal = Goal(user_id=user_id, name=name, template=template, target_amount=target_amount,
                target_date=target_date, linked_folios=linked, growth_rate=body.get("growth_rate", 0))
    gid = save_goal(goal)
    log.info(f"Goal created: {name} (id={gid}) for user {user_id}")
    return JSONResponse({"status": "ok", "goal_id": gid})


@router.put("/goals/{goal_id}")
async def update_goal(goal_id: int, request: Request, user_id: int = Depends(require_auth)):
    body = await request.json()
    goals = load_goals(user_id)
    existing = next((g for g in goals if g.id == goal_id), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Goal not found")
    existing.name = body.get("name", existing.name)
    existing.template = body.get("template", existing.template)
    existing.target_amount = body.get("target_amount", existing.target_amount)
    existing.target_date = body.get("target_date", existing.target_date)
    existing.linked_folios = body.get("linked_folios", existing.linked_folios)
    if "linked_folios" in body:
        _validate_allocations(user_id, existing.linked_folios, exclude_goal_id=goal_id)
    if body.get("growth_rate"):
        existing.growth_rate = body["growth_rate"]
    save_goal(existing)
    log.info(f"Goal updated: {existing.name} (id={goal_id})")
    return JSONResponse({"status": "ok"})


@router.delete("/goals/{goal_id}")
async def remove_goal(goal_id: int, request: Request, user_id: int = Depends(require_auth)):
    if not delete_goal(goal_id, user_id):
        raise HTTPException(status_code=404, detail="Goal not found")
    log.info(f"Goal deleted: id={goal_id} for user {user_id}")
    return JSONResponse({"status": "ok"})


@router.get("/goals/{goal_id}/detail")
async def goal_detail(goal_id: int, request: Request):
    """Return enriched goal detail with per-asset breakdown."""
    user_id = get_user_id(request) or DEMO_USER_ID
    goals = load_goals(user_id)
    goal = next((g for g in goals if g.id == goal_id), None)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    holdings = load_mf_assets(user_id)
    progress = _compute_goal_progress(goal, holdings, user_id)
    # Build enriched linked assets list
    linked_details = []
    for lf in goal.linked_folios:
        if isinstance(lf, dict) and "asset_type" in lf:
            at, aid = lf["asset_type"], lf.get("asset_id", 0)
            pct = lf.get("pct", 100)
            items = load_assets(user_id, at)
            match = next((i for i in items if i.get("id") == aid), items[0] if items else None)
            if not match:
                continue
            val = _asset_value(match) * pct / 100
            label = ASSET_LABELS.get(at, at)
            if at == "fd": label = f"FD — {match.get('bank', 'Unknown')}"
            elif at == "gold": label = f"Gold — {match.get('type', 'Physical')}"
            elif at == "esop": label = f"ESOP — {match.get('company', 'Unknown')}"
            elif at == "realestate": label = f"Property — {match.get('location', 'Unknown')}"
            elif at in ("mf", "mf_declared", "mf_sips"): label = f"MF — {match.get('scheme', match.get('scheme_name', 'Fund'))}"
            detail = {"kind": "asset", "asset_type": at, "label": label,
                      "pct": pct, "value": round(val, 2),
                      "raw_value": round(_asset_value(match), 2)}
            if at in ("mf", "mf_declared", "mf_sips"):
                detail["monthly_sip"] = float(match.get("monthly_sip", 0) or 0)
            linked_details.append(detail)
        else:
            folio_key = lf["folio"] if isinstance(lf, dict) else lf
            pct = lf.get("pct", 100) if isinstance(lf, dict) else 100
            h = next((h for h in holdings if f"{h.folio}/{h.scheme_name}" == folio_key), None)
            if not h:
                continue
            val = h.current_value * pct / 100
            linked_details.append({"kind": "mf", "folio": folio_key,
                                   "label": h.scheme_name, "pct": pct,
                                   "value": round(val, 2), "raw_value": round(h.current_value, 2)})
    tmpl = GOAL_TEMPLATES.get(goal.template, {})
    return JSONResponse({
        "id": goal.id, "name": goal.name, "template": goal.template,
        "target_amount": goal.target_amount, "target_date": goal.target_date,
        "growth_rate": goal.growth_rate, "status": goal.status,
        "created_at": goal.created_at, "description": goal.description,
        "emoji": (tmpl.get("label", "🎯 ")).split(" ")[0],
        "linked_assets": linked_details,
        **progress,
    })


@router.post("/goals/{goal_id}/accept")
async def accept_goal(goal_id: int, request: Request, user_id: int = Depends(require_auth)):
    """Accept a suggested goal — sets status to active."""
    goals = load_goals(user_id)
    goal = next((g for g in goals if g.id == goal_id), None)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    goal.status = "active"
    save_goal(goal)
    log.info(f"Goal accepted: {goal.name} (id={goal_id})")
    return JSONResponse({"status": "ok"})
