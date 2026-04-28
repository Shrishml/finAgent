"""Holdings routes — upload, view, demo, clear, suggestions, insights, analytics."""
import logging
import re
import tempfile
import traceback
from datetime import date as _date, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from finagent.connectors.base import ConnectorRegistry
from finagent.connectors.cams import CAMSConnector
from finagent.connectors.amfi import enrich_holdings, fetch_category_peers
from finagent.storage.sqlite import (
    save_holdings, load_holdings, clear_holdings, save_goal, load_goals,
    clear_goals, clear_profile, clear_conversation, clear_snapshots, clear_assets,
    save_assets,
)
from finagent.models.goal import Goal
from finagent.utils.returns import compute_holding_returns, compute_portfolio_xirr
from finagent.api.deps import get_user_id, require_auth, DEMO_USER_ID

log = logging.getLogger("finagent")
router = APIRouter(tags=["holdings"])

_registry = ConnectorRegistry()
_registry.register(CAMSConnector())

@router.post("/upload")
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


_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\[(?:[0-9;]+)m')

@router.get("/chat/history")
async def chat_history(request: Request):
    """Return conversation history for the current user."""
    user_id = get_user_id(request)
    if not user_id:
        return JSONResponse({"messages": []})
    messages = load_conversation(user_id, limit=50)
    for m in messages:
        m["content"] = _ANSI_RE.sub("", m["content"])
    return JSONResponse({"messages": messages})


@router.post("/chat")
async def chat(request: Request, query: str = Form(...)):
    """Chat endpoint — classify intent and route to agent."""
    user_id = get_user_id(request) or DEMO_USER_ID
    log.info(f"💬 User query: {query}")
    try:
        response = await handle_query(query, user_id=user_id)
        return JSONResponse({"status": "ok", "response": response})
    except Exception as e:
        log.error(f"Chat failed: {e}\n{traceback.format_exc()}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/chat/stream")
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

@router.get("/holdings")
async def get_holdings(request: Request):
    """Get current stored holdings summary. Triggers lazy enrichment if needed."""
    user_id = get_user_id(request) or DEMO_USER_ID
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



@router.post("/demo")
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

    # Seed demo profile (personal, income, expenses, insurance)
    clear_assets(user_id)
    save_assets(user_id, "personal", [{"name": "Suraj", "age": 26, "occupation": "Software Engineer",
        "employer": "Amazon", "location": "Bangalore", "marital_status": "Single",
        "kids": 0, "dependent_parents": True, "risk_tolerance": "Moderate"}])
    save_assets(user_id, "income", [{"monthly_income": 185000, "annual_bonus": 200000,
        "monthly_sip": 65000, "other_income": 0}])
    save_assets(user_id, "expenses", [{"total_monthly_expenses": 55000, "rent": 25000,
        "groceries": 8000, "utilities": 5000, "dining": 7000, "emis": 22000}])
    save_assets(user_id, "insurance", [{"term_cover": 0, "term_premium": 0,
        "health_cover": 500000, "health_premium": 12000}])
    save_assets(user_id, "meta", [{"onboarding_complete": True}])

    # Seed non-MF assets to match demo overview richness
    save_assets(user_id, "epf_ppf", [{"epf_balance": 820000, "ppf_balance": 300000}])
    save_assets(user_id, "fd", [{"amount": 500000, "bank": "SBI", "rate": 7.1, "maturity_date": "2026-06-01"}])
    save_assets(user_id, "gold", [{"value": 380000, "type": "SGB", "weight_grams": 50}])
    save_assets(user_id, "nps", [{"nps_balance": 350000, "tier": "Tier 1"}])
    save_assets(user_id, "esop", [{"vested": 332500, "company": "Amazon", "unvested": 500000}])
    save_assets(user_id, "loan", [
        {"loan_type": "Car Loan", "principal": 500000, "emi": 15000, "outstanding": 280000, "tenure_months": 48},
        {"loan_type": "Credit Card", "principal": 70000, "emi": 7000, "outstanding": 70000, "tenure_months": 12},
    ])

    log.info("Demo portfolio loaded")
    return JSONResponse({"status": "ok", "holdings_count": len(holdings), "goals_count": len(demo_goals)})



@router.post("/clear")
async def clear(request: Request):
    """Clear all user data — holdings, goals, profile, conversations."""
    user_id = get_user_id(request)
    clear_holdings(user_id)
    clear_goals(user_id)
    clear_profile(user_id)
    clear_assets(user_id)
    clear_conversation(user_id)
    clear_snapshots(user_id)
    if user_id != DEMO_USER_ID:
        clear_holdings(DEMO_USER_ID)
    log.info(f"All data cleared for user {user_id}")
    return JSONResponse({"status": "ok", "message": "All data cleared"})


@router.get("/suggestions")
async def suggestions(request: Request):
    """Generate personalized question suggestions based on portfolio."""
    user_id = get_user_id(request) or DEMO_USER_ID
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



@router.get("/insights")
async def insights(request: Request):
    """Generate portfolio insights — 10 rule-based cards (5 green + 5 amber)."""
    user_id = get_user_id(request) or DEMO_USER_ID
    holdings = load_holdings(user_id)
    if not holdings:
        return JSONResponse({"good": [], "action": []})
    # Filter zero-value funds
    holdings = [h for h in holdings if h.current_value > 0]
    return JSONResponse(_generate_insights(holdings))



@router.get("/compare/{amfi_code}")
async def compare(amfi_code: str):
    """Get category peer comparison for a fund."""
    peers = fetch_category_peers(amfi_code)
    return JSONResponse({"amfi_code": amfi_code, "peers": peers})



@router.get("/nav-history/{amfi_code}")
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

@router.get("/benchmarks")
async def list_benchmarks():
    return JSONResponse([{"key": k, "label": v} for k, v in BENCHMARK_LABELS.items()])


@router.get("/portfolio-history")
async def portfolio_history(request: Request, period: str = "1Y", benchmark: str = ""):
    """Portfolio value over time — aggregates NAV history across all holdings."""
    from finagent.analytics.nav_history import NAVHistoryEngine
    from datetime import timedelta
    user_id = get_user_id(request) or DEMO_USER_ID
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
