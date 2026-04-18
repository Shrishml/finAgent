"""Goals routes — CRUD, templates, allocations, progress projections."""
import logging
from datetime import date as _date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from finagent.models.goal import Goal, GOAL_TEMPLATES
from finagent.storage.sqlite import save_goal, load_goals, delete_goal, load_holdings
from finagent.api.deps import get_user_id, require_auth, DEMO_USER_ID

log = logging.getLogger("finagent")
router = APIRouter(tags=["goals"])


def _compute_goal_progress(goal: Goal, holdings: list) -> dict:
    """Compute progress, monthly SIP, and projection for a goal."""
    linked_value = 0.0
    monthly_sip = 0.0
    alloc_map = {}
    for lf in goal.linked_folios:
        if isinstance(lf, dict):
            alloc_map[lf["folio"]] = lf.get("pct", 100) / 100
        else:
            alloc_map[lf] = 1.0
    for h in holdings:
        key = f"{h.folio}/{h.scheme_name}"
        if key not in alloc_map:
            continue
        weight = alloc_map[key]
        linked_value += h.current_value * weight
        cutoff = _date.today() - timedelta(days=180)
        recent_investments = sum(t.amount for t in h.transactions if t.amount > 0 and t.date >= cutoff)
        monthly_sip += (recent_investments / 6) * weight

    progress_pct = (linked_value / goal.target_amount * 100) if goal.target_amount > 0 else 0
    target_dt = _date.fromisoformat(goal.target_date)
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
            if isinstance(lf, dict):
                alloc[lf["folio"]] = alloc.get(lf["folio"], 0) + lf.get("pct", 100)
            else:
                alloc[lf] = alloc.get(lf, 0) + 100
    for lf in linked_folios:
        if isinstance(lf, dict):
            key, pct = lf["folio"], lf.get("pct", 100)
        else:
            key, pct = lf, 100
        total = alloc.get(key, 0) + pct
        if total > 100:
            raise HTTPException(status_code=400, detail=f"Fund '{key}' would be {total}% allocated (max 100%)")


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
            if isinstance(lf, dict):
                alloc[lf["folio"]] = alloc.get(lf["folio"], 0) + lf.get("pct", 100)
            else:
                alloc[lf] = alloc.get(lf, 0) + 100
    return JSONResponse({"allocations": alloc})


@router.get("/goals")
async def get_goals(request: Request):
    user_id = get_user_id(request) or DEMO_USER_ID
    goals = load_goals(user_id)
    holdings = load_holdings(user_id)
    return JSONResponse({
        "goals": [{
            "id": g.id, "name": g.name, "template": g.template,
            "target_amount": g.target_amount, "target_date": g.target_date,
            "linked_folios": g.linked_folios, "growth_rate": g.growth_rate,
            "created_at": g.created_at,
            **_compute_goal_progress(g, holdings),
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
