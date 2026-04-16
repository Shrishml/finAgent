"""FinAgent — FastAPI application."""
import logging
import os
import tempfile
import traceback
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile, Cookie, Response, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from finagent.auth import create_session, get_session_user, clear_session
from finagent.config import get_config
from finagent.connectors.base import ConnectorRegistry
from finagent.connectors.cams import CAMSConnector
from finagent.connectors.amfi import enrich_holdings, fetch_category_peers
from finagent.orchestrator.engine import handle_query
from finagent.storage.sqlite import save_holdings, load_holdings, clear_holdings, get_or_create_user, save_goal, load_goals, delete_goal, clear_goals, load_profile, update_profile, clear_profile, clear_conversation, load_conversation
from finagent.models.goal import Goal, GOAL_TEMPLATES
from finagent.utils.returns import compute_holding_returns, compute_portfolio_xirr

# Logging setup
_LOG_DIR = Path(__file__).parent.parent / "data"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "finagent.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("finagent")

app = FastAPI(title="FinAgent", version="0.1.0")
DEMO_USER_ID = -1  # Reserved user_id for shared demo portfolio

# DEV_MODE: bypass OAuth, auto-create dev user. Set DEV_MODE=1 in beta environment.
_DEV_MODE = os.environ.get("DEV_MODE", "").lower() in ("1", "true")
_DEV_USER_ID: int | None = None

def _get_dev_user_id() -> int:
    global _DEV_USER_ID
    if _DEV_USER_ID is None:
        _DEV_USER_ID = get_or_create_user("dev-user", "dev@finbestie.local", "Dev User", "")
        log.info(f"DEV_MODE: created dev user with id={_DEV_USER_ID}")
    return _DEV_USER_ID


@app.middleware("http")
async def add_coop_header(request, call_next):
    response = await call_next(request)
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    return response

# Register connectors
_registry = ConnectorRegistry()
_registry.register(CAMSConnector())

# Serve UI
_UI_DIR = Path(__file__).parent.parent / "ui"
if _UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_UI_DIR)), name="static")


# DEV_MODE: magic cookie value that maps to dev user. Use in curl: -b "session=finbestie-dev"
_DEV_TOKEN = "finbestie-dev"


def _get_user_id(request: Request) -> int | None:
    """Extract user_id from session cookie. Returns None if not logged in."""
    token = request.cookies.get("session")
    if not token:
        return None
    if _DEV_MODE and token == _DEV_TOKEN:
        return _get_dev_user_id()
    user = get_session_user(token)
    if not user:
        return None
    return get_or_create_user(user["google_id"], user["email"], user["name"], user["picture"])


def require_auth(request: Request) -> int:
    """FastAPI dependency — returns user_id or raises 401."""
    user_id = _get_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id


@app.post("/auth/google")
async def auth_google(request: Request):
    """Exchange Google credential for a session cookie."""
    body = await request.json()
    credential = body.get("credential", "")
    if not credential:
        return JSONResponse({"error": "Missing credential"}, status_code=400)
    try:
        token, user_info = create_session(credential)
        user_id = get_or_create_user(user_info["google_id"], user_info["email"], user_info["name"], user_info["picture"])
        resp = JSONResponse({"status": "ok", "user": {"name": user_info["name"], "email": user_info["email"], "picture": user_info["picture"]}})
        resp.set_cookie("session", token, max_age=7 * 86400, httponly=True, samesite="lax")
        return resp
    except Exception as e:
        log.error(f"Auth failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=401)


@app.post("/auth/logout")
async def auth_logout(request: Request):
    token = request.cookies.get("session")
    if token:
        clear_session(token)
    resp = JSONResponse({"status": "ok"})
    resp.delete_cookie("session")
    return resp


@app.get("/auth/me")
async def auth_me(request: Request):
    """Check current session — returns user info or 401."""
    token = request.cookies.get("session")
    if not token:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    if _DEV_MODE and token == _DEV_TOKEN:
        return JSONResponse({"status": "ok", "user": {"name": "Dev User", "email": "dev@finbestie.local", "picture": ""}})
    user = get_session_user(token)
    if not user:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    return JSONResponse({"status": "ok", "user": {"name": user["name"], "email": user["email"], "picture": user["picture"]}})


@app.get("/", response_class=HTMLResponse)
async def landing():
    f = _UI_DIR / "index.html"
    return f.read_text() if f.exists() else "<h1>FinBestie</h1>"

@app.get("/app", response_class=HTMLResponse)
@app.get("/demo", response_class=HTMLResponse)
async def dashboard():
    f = _UI_DIR / "app.html"
    return f.read_text() if f.exists() else "<h1>FinBestie</h1>"


@app.get("/about", response_class=HTMLResponse)
async def about():
    f = _UI_DIR / "about.html"
    return f.read_text() if f.exists() else "<h1>About FinBestie</h1>"

@app.get("/help/cas", response_class=HTMLResponse)
async def help_cas():
    f = _UI_DIR / "help-cas.html"
    return f.read_text() if f.exists() else "<h1>CAS Help</h1>"

@app.get("/changelog")
async def changelog():
    import json
    f = Path(__file__).parent.parent / "ui" / "changelog.json"
    return json.loads(f.read_text()) if f.exists() else []

@app.post("/upload")
async def upload(request: Request, user_id: int = Depends(require_auth), file: UploadFile = File(...), password: str = Form(""), merge: str = Form("false")):
    """Upload a CAMS/KFintech PDF and parse it."""
    do_merge = merge.lower() == "true"
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        domain, holdings = _registry.parse(tmp_path, password)
        log.info(f"Parsed {len(holdings)} holdings from {file.filename}")
        try:
            holdings = enrich_holdings(holdings)
            log.info("AMFI enrichment complete")
        except Exception as e:
            log.warning(f"AMFI enrichment failed (continuing without): {e}")
        save_holdings(holdings, user_id, merge=do_merge)
        return JSONResponse({
            "status": "ok",
            "domain": domain,
            "holdings_count": len(holdings),
            "schemes": [h.scheme_name for h in holdings],
            "merged": do_merge,
        })
    except Exception as e:
        log.error(f"Upload failed: {e}\n{traceback.format_exc()}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    finally:
        tmp_path.unlink(missing_ok=True)


@app.get("/chat/history")
async def chat_history(request: Request):
    """Return conversation history for the current user."""
    user_id = _get_user_id(request)
    if not user_id:
        return JSONResponse({"messages": []})
    messages = load_conversation(user_id, limit=50)
    return JSONResponse({"messages": messages})


@app.post("/chat")
async def chat(request: Request, query: str = Form(...)):
    """Chat endpoint — classify intent and route to agent."""
    user_id = _get_user_id(request) or DEMO_USER_ID
    log.info(f"💬 User query: {query}")
    try:
        response = await handle_query(query, user_id=user_id)
        return JSONResponse({"status": "ok", "response": response})
    except Exception as e:
        log.error(f"Chat failed: {e}\n{traceback.format_exc()}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.post("/chat/stream")
async def chat_stream(request: Request, user_id: int = Depends(require_auth), query: str = Form(...)):
    """Streaming chat endpoint — returns SSE events as LLM generates tokens."""
    from finagent.orchestrator.engine import handle_query_stream
    log.info(f"💬 [stream] User query: {query}")

    async def event_generator():
        try:
            async for chunk in handle_query_stream(query, user_id=user_id):
                yield f"data: {chunk}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            log.error(f"Stream failed: {e}")
            yield f"data: [ERROR] {e}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/holdings")
async def get_holdings(request: Request):
    """Get current stored holdings summary. Triggers lazy enrichment if needed."""
    user_id = _get_user_id(request) or DEMO_USER_ID
    holdings = load_holdings(user_id)
    if holdings and any(h.expense_ratio == 0 and h.amfi_code for h in holdings):
        try:
            holdings = enrich_holdings(holdings)
            save_holdings(holdings, user_id)
            log.info("Lazy enrichment on /holdings complete")
        except Exception as e:
            log.debug(f"Lazy enrichment failed: {e}")
    return JSONResponse({
        "count": len(holdings),
        "portfolio_xirr": compute_portfolio_xirr(holdings),
        "holdings": [
            {
                "scheme": h.scheme_name, "folio": h.folio, "value": h.current_value,
                "invested": h.invested_value, "plan": h.plan, "expense_ratio": h.expense_ratio,
                "amfi_code": h.amfi_code, "category": h.category, "units": h.units, "nav": h.nav,
                "nav_date": h.nav_date, "day_change": h.day_change, "day_change_pct": h.day_change_pct,
                "morningstar": h.morningstar, "aum": h.aum, "risk_label": h.risk_label,
                **compute_holding_returns(h),
            }
            for h in holdings
        ],
    })


@app.post("/demo")
async def demo():
    """Load a demo portfolio for users to explore without uploading."""
    user_id = DEMO_USER_ID
    from datetime import date as _date
    from finagent.models.mf import MFHolding, MFTransaction
    _t = lambda d, amt, units: MFTransaction(date=_date.fromisoformat(d), description="SIP", amount=amt, units=units, type="SIP")

    # Monthly SIPs from Jan 2024 — realistic NAV progression per fund
    # Parag Parikh Flexi Cap: ₹5K/mo SIP, NAV ~72→82 over 18 months
    pp_txns = [_t(f"2024-{m:02d}-15", 5000, round(5000/nav, 2)) for m, nav in
               [(1,72),(2,73),(3,71),(4,74),(5,73),(6,75),(7,76),(8,74),(9,77),(10,78),(11,76),(12,79)]]
    pp_txns += [_t(f"2025-{m:02d}-15", 5000, round(5000/nav, 2)) for m, nav in
                [(1,80),(2,78),(3,81),(4,82),(5,80),(6,83)]]
    pp_units = sum(t.units for t in pp_txns)  # ~1140

    # HDFC Mid-Cap: ₹5K/mo SIP, NAV ~160→185
    hdfc_txns = [_t(f"2024-{m:02d}-10", 5000, round(5000/nav, 2)) for m, nav in
                 [(1,160),(2,162),(3,158),(4,165),(5,163),(6,168),(7,170),(8,166),(9,172),(10,175),(11,173),(12,178)]]
    hdfc_txns += [_t(f"2025-{m:02d}-10", 5000, round(5000/nav, 2)) for m, nav in
                  [(1,180),(2,176),(3,183),(4,185),(5,182),(6,188)]]
    hdfc_units = sum(t.units for t in hdfc_txns)

    # SBI Small Cap: ₹3K/mo SIP, NAV ~140→158
    sbi_txns = [_t(f"2024-{m:02d}-01", 3000, round(3000/nav, 2)) for m, nav in
                [(4,140),(5,142),(6,138),(7,145),(8,143),(9,148),(10,150),(11,147),(12,152)]]
    sbi_txns += [_t(f"2025-{m:02d}-01", 3000, round(3000/nav, 2)) for m, nav in
                 [(1,154),(2,150),(3,156),(4,158),(5,155),(6,160)]]
    sbi_units = sum(t.units for t in sbi_txns)

    # ICICI Balanced Advantage: ₹10K/mo SIP, NAV ~58→66
    icici_txns = [_t(f"2024-{m:02d}-15", 10000, round(10000/nav, 2)) for m, nav in
                  [(1,58),(2,59),(3,57),(4,60),(5,59),(6,61),(7,62),(8,60),(9,63),(10,64),(11,62),(12,65)]]
    icici_txns += [_t(f"2025-{m:02d}-15", 10000, round(10000/nav, 2)) for m, nav in
                   [(1,66),(2,64),(3,67),(4,68),(5,66),(6,69)]]
    icici_units = sum(t.units for t in icici_txns)

    # Axis ELSS: ₹12.5K lump 2x/year (tax saving)
    elss_txns = [_t("2024-02-01", 12500, round(12500/78, 2)), _t("2024-09-01", 12500, round(12500/82, 2)),
                 _t("2025-02-01", 12500, round(12500/85, 2))]
    elss_units = sum(t.units for t in elss_txns)

    # HDFC Corporate Bond: ₹25K lump 2x (debt allocation)
    bond_txns = [_t("2024-01-01", 25000, round(25000/28.5, 2)), _t("2024-07-01", 25000, round(25000/29.0, 2)),
                 _t("2025-01-01", 25000, round(25000/29.5, 2))]
    bond_units = sum(t.units for t in bond_txns)

    holdings = [
        MFHolding(scheme_name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth", folio="DEMO-001", amc="PPFAS", amfi_code="122639", plan="direct",
                  units=pp_units, nav=83, current_value=pp_units*83, invested_value=len(pp_txns)*5000,
                  transactions=pp_txns),
        MFHolding(scheme_name="HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth", folio="DEMO-002", amc="HDFC", amfi_code="118989", plan="direct",
                  units=hdfc_units, nav=188, current_value=hdfc_units*188, invested_value=len(hdfc_txns)*5000,
                  transactions=hdfc_txns),
        MFHolding(scheme_name="SBI Small Cap Fund - Direct Plan - Growth", folio="DEMO-003", amc="SBI", amfi_code="125497", plan="direct",
                  units=sbi_units, nav=160, current_value=sbi_units*160, invested_value=len(sbi_txns)*3000,
                  transactions=sbi_txns),
        MFHolding(scheme_name="ICICI Prudential Balanced Advantage Fund - Direct Plan - Growth", folio="DEMO-004", amc="ICICI", amfi_code="120377", plan="direct",
                  units=icici_units, nav=69, current_value=icici_units*69, invested_value=len(icici_txns)*10000,
                  transactions=icici_txns),
        MFHolding(scheme_name="Axis ELSS Tax Saver Fund - Direct Plan - Growth", folio="DEMO-005", amc="Axis", amfi_code="120503", plan="direct",
                  units=elss_units, nav=88, current_value=elss_units*88, invested_value=37500, tax_section="80C",
                  transactions=elss_txns),
        MFHolding(scheme_name="HDFC Corporate Bond Fund - Direct Plan - Growth", folio="DEMO-006", amc="HDFC", amfi_code="118987", plan="direct",
                  units=bond_units, nav=30, current_value=bond_units*30, invested_value=75000,
                  transactions=bond_txns),
    ]
    clear_holdings(user_id)
    try:
        holdings = enrich_holdings(holdings)
    except Exception as e:
        log.warning(f"Demo enrichment failed: {e}")
    save_holdings(holdings, user_id)
    # Seed demo goals
    clear_goals(user_id)
    from finagent.models.goal import Goal as GoalModel
    demo_goals = [
        GoalModel(user_id=user_id, name="Retirement at 50", template="retirement",
                  target_amount=5_000_000, target_date="2048-01-01",
                  linked_folios=[{"folio": "DEMO-001/Parag Parikh Flexi Cap Fund - Direct Plan - Growth", "pct": 40},
                                 {"folio": "DEMO-004/ICICI Prudential Balanced Advantage Fund - Direct Plan - Growth", "pct": 60}]),
        GoalModel(user_id=user_id, name="Dream Home", template="house",
                  target_amount=3_000_000, target_date="2030-06-01",
                  linked_folios=[{"folio": "DEMO-002/HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth", "pct": 50},
                                 {"folio": "DEMO-006/HDFC Corporate Bond Fund - Direct Plan - Growth", "pct": 50}]),
        GoalModel(user_id=user_id, name="Emergency Fund", template="emergency",
                  target_amount=300_000, target_date="2027-01-01",
                  linked_folios=[{"folio": "DEMO-006/HDFC Corporate Bond Fund - Direct Plan - Growth", "pct": 100}]),
    ]
    for g in demo_goals:
        save_goal(g)
    log.info("Demo portfolio loaded")
    return JSONResponse({"status": "ok", "holdings_count": len(holdings), "goals_count": len(demo_goals)})


@app.post("/clear")
async def clear(request: Request):
    """Clear all user data — holdings, goals, profile, conversations."""
    user_id = _get_user_id(request)
    clear_holdings(user_id)
    clear_goals(user_id)
    clear_profile(user_id)
    clear_conversation(user_id)
    if user_id != DEMO_USER_ID:
        clear_holdings(DEMO_USER_ID)
    log.info(f"All data cleared for user {user_id}")
    return JSONResponse({"status": "ok", "message": "All data cleared"})



# --- Goals ---

def _compute_goal_progress(goal: Goal, holdings: list) -> dict:
    """Compute progress, monthly SIP, and projection for a goal."""
    from datetime import date as _date, timedelta
    import math

    # Sum current value of linked holdings (weighted by allocation %)
    linked_value = 0.0
    monthly_sip = 0.0
    # Build lookup: folio_key → allocation pct
    alloc_map = {}
    for lf in goal.linked_folios:
        if isinstance(lf, dict):
            alloc_map[lf["folio"]] = lf.get("pct", 100) / 100
        else:
            alloc_map[lf] = 1.0  # backward compat with old string format
    for h in holdings:
        key = f"{h.folio}/{h.scheme_name}"
        if key not in alloc_map:
            continue
        weight = alloc_map[key]
        linked_value += h.current_value * weight
        # Detect SIP: average monthly investment over last 6 months
        cutoff = _date.today() - timedelta(days=180)
        recent_investments = sum(
            t.amount for t in h.transactions
            if t.amount > 0 and t.date >= cutoff
        )
        monthly_sip += (recent_investments / 6) * weight

    progress_pct = (linked_value / goal.target_amount * 100) if goal.target_amount > 0 else 0
    target_dt = _date.fromisoformat(goal.target_date)
    months_left = max(0, (target_dt.year - _date.today().year) * 12 + target_dt.month - _date.today().month)

    # Project future value: FV = PV*(1+r)^n + SIP*[((1+r)^n - 1)/r]
    monthly_rate = goal.growth_rate / 12
    if monthly_rate > 0 and months_left > 0:
        fv_lump = linked_value * (1 + monthly_rate) ** months_left
        fv_sip = monthly_sip * (((1 + monthly_rate) ** months_left - 1) / monthly_rate)
        projected_value = fv_lump + fv_sip
    else:
        projected_value = linked_value + monthly_sip * months_left

    # Estimate months to reach target (binary search)
    projected_months = None
    if monthly_rate > 0 and (linked_value > 0 or monthly_sip > 0):
        for m in range(1, 600):  # up to 50 years
            fv = linked_value * (1 + monthly_rate) ** m + monthly_sip * (((1 + monthly_rate) ** m - 1) / monthly_rate)
            if fv >= goal.target_amount:
                projected_months = m
                break

    on_track = projected_value >= goal.target_amount if months_left > 0 else linked_value >= goal.target_amount

    # SIP gap: how much more monthly SIP needed to hit target
    sip_gap = 0.0
    if not on_track and months_left > 0 and monthly_rate > 0:
        # target = PV*(1+r)^n + (SIP+gap)*[((1+r)^n - 1)/r]
        fv_lump = linked_value * (1 + monthly_rate) ** months_left
        annuity_factor = ((1 + monthly_rate) ** months_left - 1) / monthly_rate
        if annuity_factor > 0:
            required_sip = (goal.target_amount - fv_lump) / annuity_factor
            sip_gap = max(0, required_sip - monthly_sip)

    return {
        "current_value": round(linked_value, 2),
        "progress_pct": round(min(progress_pct, 100), 1),
        "monthly_sip": round(monthly_sip, 2),
        "projected_value": round(projected_value, 2),
        "months_left": months_left,
        "projected_months": projected_months,
        "on_track": on_track,
        "sip_gap": round(sip_gap, 2),
    }


@app.get("/goals/templates")
async def goal_templates():
    """Return available goal templates with defaults."""
    return JSONResponse({
        "templates": {k: v for k, v in GOAL_TEMPLATES.items()}
    })


@app.get("/goals/allocations")
async def goal_allocations(request: Request):
    """Return total allocated % per fund across all goals. Excludes a specific goal if ?exclude=ID."""
    user_id = _get_user_id(request) or DEMO_USER_ID
    exclude_id = request.query_params.get("exclude")
    exclude_id = int(exclude_id) if exclude_id else None
    goals = load_goals(user_id)
    alloc = {}  # folio_key → total allocated pct
    for g in goals:
        if g.id == exclude_id:
            continue
        for lf in g.linked_folios:
            if isinstance(lf, dict):
                key = lf["folio"]
                alloc[key] = alloc.get(key, 0) + lf.get("pct", 100)
            else:
                alloc[lf] = alloc.get(lf, 0) + 100
    return JSONResponse({"allocations": alloc})


@app.get("/goals")
async def get_goals(request: Request):
    """List user's goals with progress projections."""
    user_id = _get_user_id(request) or DEMO_USER_ID
    goals = load_goals(user_id)
    holdings = load_holdings(user_id)
    return JSONResponse({
        "goals": [
            {
                "id": g.id, "name": g.name, "template": g.template,
                "target_amount": g.target_amount, "target_date": g.target_date,
                "linked_folios": g.linked_folios, "growth_rate": g.growth_rate,
                "created_at": g.created_at,
                **_compute_goal_progress(g, holdings),
            }
            for g in goals
        ]
    })


def _validate_allocations(user_id: int, linked_folios: list, exclude_goal_id: int | None = None):
    """Check that no fund exceeds 100% allocation across all goals."""
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


@app.post("/goals")
async def create_goal(request: Request, user_id: int = Depends(require_auth)):
    """Create a new goal."""
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
    goal = Goal(
        user_id=user_id, name=name, template=template,
        target_amount=target_amount, target_date=target_date,
        linked_folios=linked,
        growth_rate=body.get("growth_rate", 0),
    )
    gid = save_goal(goal)
    log.info(f"Goal created: {name} (id={gid}) for user {user_id}")
    return JSONResponse({"status": "ok", "goal_id": gid})


@app.put("/goals/{goal_id}")
async def update_goal(goal_id: int, request: Request, user_id: int = Depends(require_auth)):
    """Update an existing goal."""
    body = await request.json()
    goals = load_goals(user_id)
    existing = next((g for g in goals if g.id == goal_id), None)
    if not existing:
        raise HTTPException(status_code=404, detail="Goal not found")
    # Apply updates
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


@app.delete("/goals/{goal_id}")
async def remove_goal(goal_id: int, request: Request, user_id: int = Depends(require_auth)):
    """Delete a goal."""
    if not delete_goal(goal_id, user_id):
        raise HTTPException(status_code=404, detail="Goal not found")
    log.info(f"Goal deleted: id={goal_id} for user {user_id}")
    return JSONResponse({"status": "ok"})


@app.post("/dev/seed")
async def dev_seed():
    """Seed dev user with demo holdings. Only available in DEV_MODE."""
    if not _DEV_MODE:
        raise HTTPException(status_code=404)
    # Load demo holdings, save under dev user
    demo_holdings = load_holdings(DEMO_USER_ID)
    if not demo_holdings:
        # Trigger demo creation first
        await demo()
        demo_holdings = load_holdings(DEMO_USER_ID)
    dev_uid = _get_dev_user_id()
    clear_holdings(dev_uid)
    save_holdings(demo_holdings, dev_uid)
    # Seed sample goals
    clear_goals(dev_uid)
    from finagent.models.goal import Goal as GoalModel
    sample_goals = [
        GoalModel(user_id=dev_uid, name="Retirement at 50", template="retirement",
                  target_amount=5_000_000, target_date="2048-01-01",
                  linked_folios=[{"folio": "DEMO-001/Parag Parikh Flexi Cap Fund - Direct Plan - Growth", "pct": 40},
                                 {"folio": "DEMO-004/ICICI Prudential Balanced Advantage Fund - Direct Plan - Growth", "pct": 60}]),
        GoalModel(user_id=dev_uid, name="Dream Home", template="house",
                  target_amount=3_000_000, target_date="2030-06-01",
                  linked_folios=[{"folio": "DEMO-002/HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth", "pct": 50},
                                 {"folio": "DEMO-006/HDFC Corporate Bond Fund - Direct Plan - Growth", "pct": 50}]),
        GoalModel(user_id=dev_uid, name="Emergency Fund", template="emergency",
                  target_amount=300_000, target_date="2027-01-01",
                  linked_folios=[{"folio": "DEMO-006/HDFC Corporate Bond Fund - Direct Plan - Growth", "pct": 100}]),
    ]
    for g in sample_goals:
        save_goal(g)
    goal_count = len(sample_goals)
    log.info(f"DEV_MODE: seeded {len(demo_holdings)} holdings + {goal_count} goals for dev user {dev_uid}")
    return JSONResponse({"status": "ok", "holdings_count": len(demo_holdings), "goals_count": goal_count})


@app.post("/dev/reset")
async def dev_reset():
    """Clear dev user data. Only available in DEV_MODE."""
    if not _DEV_MODE:
        raise HTTPException(status_code=404)
    dev_uid = _get_dev_user_id()
    clear_holdings(dev_uid)
    clear_goals(dev_uid)
    log.info(f"DEV_MODE: cleared dev user {dev_uid}")
    return JSONResponse({"status": "ok"})


def _build_action_items(profile, user_id):
    """Generate prioritized action items based on profile gaps."""
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


@app.get("/profile")
async def get_profile(request: Request):
    """Return user's financial profile and health score."""
    user_id = _get_user_id(request) or DEMO_USER_ID
    profile = load_profile(user_id)
    if not profile:
        return JSONResponse({"profile": None, "onboarding_complete": False})

    # Health score: 0-100 based on data completeness and financial health
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
            "monthly_income": profile.monthly_income,
            "monthly_expenses": profile.monthly_expenses,
            "savings_rate": profile.savings_rate,
            "occupation": profile.occupation,
            "employer": profile.employer,
            "age": profile.age,
            "dependents": profile.dependents,
            "location": profile.location,
            "marital_status": profile.marital_status,
            "kids": profile.kids,
            "risk_tolerance": profile.risk_tolerance,
            "loans": profile.loans,
            "total_emi": profile.total_emi,
            "term_cover": profile.term_cover,
            "health_cover": profile.health_cover,
            "health_employer_only": profile.health_employer_only,
            "pillars_completed": profile.pillars_completed,
            "pillars_skipped": profile.pillars_skipped,
            "onboarding_complete": profile.onboarding_complete,
            "goals_mentioned": profile.goals_mentioned,
        },
        "health_score": min(score, 100),
        "flags": flags,
        "action_items": _build_action_items(profile, user_id),
        "onboarding_complete": profile.onboarding_complete,
    })


@app.put("/profile")
async def save_profile_endpoint(request: Request, user_id: int = Depends(require_auth)):
    """Save/update user profile from onboarding cards."""
    body = await request.json()
    # Whitelist allowed fields
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


@app.get("/suggestions")
async def suggestions(request: Request):
    """Generate personalized question suggestions based on portfolio."""
    user_id = _get_user_id(request) or DEMO_USER_ID
    holdings = load_holdings(user_id)
    if not holdings:
        return JSONResponse({"suggestions": [
            "Upload a CAMS PDF to get started",
        ]})

    questions = []
    total = sum(h.current_value for h in holdings)
    regular = [h for h in holdings if h.plan == "regular"]
    high_er = [h for h in holdings if h.expense_ratio > 0.01]
    small_caps = [h for h in holdings if "small" in h.scheme_name.lower()]

    questions.append(f"Give me a summary of my ₹{total:,.0f} portfolio")
    questions.append("What are my expense ratios?")

    if regular:
        questions.append(f"I have {len(regular)} regular plan fund(s) — should I switch to direct?")
    if high_er:
        questions.append(f"Which of my funds has the highest expense ratio?")
    if len(small_caps) > 1:
        questions.append(f"I have {len(small_caps)} small cap funds — is that too many?")
    if len(holdings) > 5:
        questions.append("Do any of my funds overlap?")

    questions.append("Which fund is my best performer?")
    questions.append("Are there cheaper alternatives to my funds?")
    return JSONResponse({"suggestions": questions[:6]})


def _classify_asset(cat: str) -> str:
    c = (cat or "").lower().replace("-", " ")
    if any(k in c for k in ("equity", "elss", "large cap", "mid cap", "small cap", "flexi cap", "multi cap")):
        return "Equity"
    if any(k in c for k in ("debt", "liquid", "money market", "gilt", "overnight")):
        return "Debt"
    if any(k in c for k in ("hybrid", "allocation", "balanced", "arbitrage")):
        return "Hybrid"
    return "Other"


def _short_name(s: str) -> str:
    import re
    return re.sub(r" - Direct.*| - Regular.*| Plan.*| Growth.*", "", s)[:50]


def _generate_insights(holdings: list) -> dict:
    """Generate 10 portfolio insights (5 green + 5 amber) from holdings."""
    good, action = [], []
    total = sum(h.current_value for h in holdings)
    xirrs = [h for h in holdings if h.xirr]
    avg_xirr = (sum(h.xirr for h in xirrs) / len(xirrs)) if xirrs else 0

    # === GOOD (What's working) ===
    best = max((h for h in holdings if h.xirr), key=lambda h: h.xirr, default=None)
    if best:
        good.append({"title": "Top performer", "desc": f"{_short_name(best.scheme_name)} at {best.xirr:+.1f}% XIRR", "q": f"Tell me more about {_short_name(best.scheme_name)}"})

    regular = [h for h in holdings if h.plan == "regular"]
    if not regular and len(holdings) > 1:
        good.append({"title": "All direct plans", "desc": "No commission leakage — you're keeping more of your returns", "q": "How much do direct plans save me?"})

    sip_funds = [h for h in holdings if len(h.transactions) >= 3]
    if len(sip_funds) >= 2:
        good.append({"title": "Consistent SIPs", "desc": f"{len(sip_funds)} funds with regular investments — consistency is your biggest edge", "q": "How are my SIPs performing?"})

    asset_map = {}
    for h in holdings:
        a = _classify_asset(h.category)
        if a != "Other":
            asset_map[a] = asset_map.get(a, 0) + h.current_value
    if len(asset_map) >= 3:
        good.append({"title": "Well diversified", "desc": f"Portfolio covers {', '.join(asset_map.keys())}", "q": "Is my diversification good enough?"})

    if avg_xirr > 12:
        good.append({"title": "Beating the market", "desc": f"Portfolio avg XIRR {avg_xirr:.1f}% vs Nifty 50 long-term ~12%", "q": "How does my portfolio compare to Nifty 50?"})

    # === ACTIONABLE (Worth a look) ===
    returns = {h.scheme_name: compute_holding_returns(h) for h in holdings}
    under = [h for h in holdings if (returns[h.scheme_name].get("return_pct", 0) < 0) or (h.xirr and h.xirr < avg_xirr - 5)]
    if under:
        descs = [f"{_short_name(h.scheme_name)} ({h.xirr:+.1f}%)" if h.xirr else _short_name(h.scheme_name) for h in under[:3]]
        action.append({"title": f"{len(under)} underperforming fund{'s' if len(under) > 1 else ''}", "desc": ", ".join(descs), "q": "Which funds should I replace?"})

    if regular:
        action.append({"title": f"{len(regular)} regular plan fund{'s' if len(regular) > 1 else ''}", "desc": "You're paying hidden commission on these", "q": "Should I switch from regular to direct plans?"})

    if len(holdings) > 7:
        action.append({"title": f"{len(holdings)} funds — possible overlap", "desc": "Some funds may be doing the same job. Consider consolidating.", "q": "Do any of my funds overlap?"})

    sc_val = sum(h.current_value for h in holdings if "small" in (h.category or "").lower())
    if total > 0 and sc_val / total > 0.3:
        action.append({"title": f"{sc_val / total * 100:.0f}% in small caps", "desc": "High growth but high volatility — does this match your risk appetite?", "q": "Do I have too much in small caps?"})

    debt_val = sum(h.current_value for h in holdings if _classify_asset(h.category) == "Debt")
    if debt_val == 0 and len(holdings) > 2:
        action.append({"title": "No debt allocation", "desc": "100% equity — consider adding debt funds for stability", "q": "Should I add debt funds to my portfolio?"})

    return {"good": good, "action": action}


@app.get("/insights")
async def insights(request: Request):
    """Generate portfolio insights — 10 rule-based cards (5 green + 5 amber)."""
    user_id = _get_user_id(request) or DEMO_USER_ID
    holdings = load_holdings(user_id)
    if not holdings:
        return JSONResponse({"good": [], "action": []})
    # Filter zero-value funds
    holdings = [h for h in holdings if h.current_value > 0]
    return JSONResponse(_generate_insights(holdings))


@app.get("/compare/{amfi_code}")
async def compare(amfi_code: str):
    """Get category peer comparison for a fund."""
    peers = fetch_category_peers(amfi_code)
    return JSONResponse({"amfi_code": amfi_code, "peers": peers})


@app.get("/nav-history/{amfi_code}")
async def nav_history(amfi_code: str, period: str = "1Y"):
    """Get NAV history for performance chart. period: 1M, 3M, 6M, 1Y, 3Y, 5Y, MAX."""
    from finagent.analytics.nav_history import NAVHistoryEngine
    from datetime import timedelta, date as _date
    engine = NAVHistoryEngine()
    history = engine.fetch(amfi_code)
    if not history:
        return JSONResponse({"dates": [], "navs": []})
    periods = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "3Y": 1095, "5Y": 1825}
    if period != "MAX" and period in periods:
        cutoff = history[-1][0] - timedelta(days=periods[period])
        history = [(d, n) for d, n in history if d >= cutoff]
    # Downsample for large datasets (keep ~200 points max)
    step = max(1, len(history) // 200)
    sampled = history[::step]
    if sampled[-1] != history[-1]:
        sampled.append(history[-1])
    return JSONResponse({
        "dates": [d.isoformat() for d, _ in sampled],
        "navs": [round(n, 2) for _, n in sampled],
    })


# AMFI codes for popular index funds (used as benchmark proxies)
BENCHMARK_CODES = {
    "nifty50": "120716",       # UTI Nifty 50 Index Fund - Direct Growth
    "nifty100": "120684",      # ICICI Prudential Nifty Next 50 Index Fund - Direct Growth
    "midcap": "148726",        # Nippon India Nifty Midcap 150 Index Fund - Direct Growth
    "smallcap": "148519",      # Nippon India Nifty Smallcap 250 Index Fund - Direct Growth
    "gold": "140088",          # Nippon India ETF Gold BeES
}
BENCHMARK_LABELS = {
    "nifty50": "Nifty 50",
    "nifty100": "Next 50",
    "midcap": "Midcap 150",
    "smallcap": "Smallcap 250",
    "gold": "Gold",
}

@app.get("/benchmarks")
async def list_benchmarks():
    return JSONResponse([{"key": k, "label": v} for k, v in BENCHMARK_LABELS.items()])

@app.get("/portfolio-history")
async def portfolio_history(request: Request, period: str = "1Y", benchmark: str = ""):
    """Portfolio value over time — aggregates NAV history across all holdings."""
    from finagent.analytics.nav_history import NAVHistoryEngine
    from datetime import timedelta
    user_id = _get_user_id(request) or DEMO_USER_ID
    holdings = load_holdings(user_id)
    if not holdings:
        return JSONResponse({"dates": [], "values": [], "invested": []})

    engine = NAVHistoryEngine()
    periods = {"1M": 30, "3M": 90, "6M": 180, "1Y": 365, "3Y": 1095, "5Y": 1825}

    # Build cumulative invested timeline from transactions
    invest_events = []  # (date, amount)
    for h in holdings:
        for t in h.transactions:
            invest_events.append((t.date, t.amount))  # positive=purchase, negative=redemption
    invest_events.sort(key=lambda x: x[0])
    cum_invested = {}
    running = 0
    for d, amt in invest_events:
        running += amt
        cum_invested[d] = running

    # Find earliest transaction date as chart start
    first_txn = invest_events[0][0] if invest_events else None

    # Fetch NAV history for each holding
    fund_data = []
    for h in holdings:
        if not h.amfi_code:
            continue
        hist = engine.fetch(h.amfi_code)
        if not hist:
            continue
        # Build units timeline from transactions
        unit_events = sorted([(t.date, t.units or 0) for t in h.transactions], key=lambda x: x[0])
        fund_data.append({"unit_events": unit_events, "history": dict(hist)})

    if not fund_data:
        return JSONResponse({"dates": [], "values": [], "invested": []})

    # Date range: from first transaction to latest NAV
    all_dates = set()
    for fd in fund_data:
        all_dates.update(fd["history"].keys())
    all_dates = sorted(d for d in all_dates if (first_txn is None or d >= first_txn))

    if period != "MAX" and period in periods:
        cutoff = all_dates[-1] - timedelta(days=periods[period])
        all_dates = [d for d in all_dates if d >= cutoff]

    # Compute portfolio value + invested for each date
    dates_out, values_out, invested_out = [], [], []
    last_nav = {i: None for i in range(len(fund_data))}
    cum_units = {i: 0.0 for i in range(len(fund_data))}
    unit_idx = {i: 0 for i in range(len(fund_data))}
    running_invested = 0
    invest_dates = sorted(cum_invested.keys())
    invest_idx = 0
    for d in all_dates:
        # Update cumulative invested
        while invest_idx < len(invest_dates) and invest_dates[invest_idx] <= d:
            running_invested = cum_invested[invest_dates[invest_idx]]
            invest_idx += 1
        # Update cumulative units per fund and compute value
        val = 0
        for i, fd in enumerate(fund_data):
            while unit_idx[i] < len(fd["unit_events"]) and fd["unit_events"][unit_idx[i]][0] <= d:
                cum_units[i] += fd["unit_events"][unit_idx[i]][1]
                unit_idx[i] += 1
            nav = fd["history"].get(d)
            if nav is not None:
                last_nav[i] = nav
            if last_nav[i] is not None and cum_units[i] > 0:
                val += cum_units[i] * last_nav[i]
        if val > 0 and running_invested > 0:
            dates_out.append(d)
            values_out.append(val)
            invested_out.append(running_invested)

    # Downsample to ~200 points
    if len(dates_out) > 200:
        step = len(dates_out) // 200
        sampled_idx = list(range(0, len(dates_out), step))
        if sampled_idx[-1] != len(dates_out) - 1:
            sampled_idx.append(len(dates_out) - 1)
    else:
        sampled_idx = list(range(len(dates_out)))

    # --- Benchmark: money-weighted comparison ---
    benchmarks = {}
    bench_keys = [b.strip().lower() for b in benchmark.split(",") if b.strip().lower() in BENCHMARK_CODES]
    if bench_keys and invest_events:
        for bk in bench_keys:
            bcode = BENCHMARK_CODES[bk]
            bhist = engine.fetch(bcode)
            if not bhist:
                continue
            bnav = dict(bhist)
            # Simulate: for each real transaction, buy equivalent ₹ of benchmark
            bench_units_events = []  # (date, units)
            for d, amt in invest_events:
                # Find nearest NAV on or after transaction date
                nav = None
                for offset in range(0, 7):
                    candidate = d + timedelta(days=offset)
                    if candidate in bnav:
                        nav = bnav[candidate]
                        break
                if nav and nav > 0:
                    bench_units_events.append((d, amt / nav))  # same ₹, buy benchmark units
            # Walk same dates, compute benchmark portfolio value
            bench_vals = []
            bcum = 0.0
            buidx = 0
            blast_nav = None
            for d in (dates_out[i] for i in sampled_idx):
                while buidx < len(bench_units_events) and bench_units_events[buidx][0] <= d:
                    bcum += bench_units_events[buidx][1]
                    buidx += 1
                nav = bnav.get(d)
                if nav is not None:
                    blast_nav = nav
                if blast_nav and bcum > 0:
                    bench_vals.append(round(bcum * blast_nav, 2))
                else:
                    bench_vals.append(None)
            benchmarks[bk] = {"label": BENCHMARK_LABELS[bk], "values": bench_vals}

    return JSONResponse({
        "dates": [dates_out[i].isoformat() for i in sampled_idx],
        "values": [round(values_out[i], 2) for i in sampled_idx],
        "invested": [round(invested_out[i], 2) for i in sampled_idx],
        "benchmarks": benchmarks,
    })

def main():
    cfg = get_config()
    server = cfg.get("server", {})
    host = server.get("host", "0.0.0.0")
    port = server.get("port", 8000)
    print(f"🚀 FinAgent starting at http://{host}:{port}")
    if _DEV_MODE:
        print("⚠️  DEV_MODE enabled — authentication bypassed")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
