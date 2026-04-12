"""FinAgent — FastAPI application."""
import logging
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
from finagent.storage.sqlite import save_holdings, load_holdings, clear_holdings, get_or_create_user
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


def _get_user_id(request: Request) -> int | None:
    """Extract user_id from session cookie. Returns None if not logged in."""
    token = request.cookies.get("session")
    if not token:
        return None
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
    _t = lambda d, amt, units, desc="SIP": MFTransaction(date=_date.fromisoformat(d), description=desc, amount=amt, units=units, type="SIP" if amt > 0 else "REDEMPTION")
    holdings = [
        MFHolding(scheme_name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth", folio="DEMO-001", amc="PPFAS", amfi_code="122639", plan="direct",
                  units=1200.5, nav=72.5, current_value=87036.25, invested_value=72000.0,
                  transactions=[_t("2024-01-15", 5000, 83.3), _t("2024-06-15", 5000, 76.9), _t("2025-01-15", 5000, 71.4), _t("2025-06-15", 5000, 68.5)]),
        MFHolding(scheme_name="HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth", folio="DEMO-002", amc="HDFC", amfi_code="118989", plan="direct",
                  units=450.2, nav=165.3, current_value=74418.06, invested_value=60000.0,
                  transactions=[_t("2024-03-10", 10000, 75.0), _t("2024-09-10", 10000, 66.7), _t("2025-03-10", 10000, 62.5)]),
        MFHolding(scheme_name="SBI Small Cap Fund - Direct Plan - Growth", folio="DEMO-003", amc="SBI", amfi_code="125497", plan="direct",
                  units=310.8, nav=148.2, current_value=46060.56, invested_value=40000.0,
                  transactions=[_t("2024-04-01", 10000, 80.0), _t("2025-01-01", 10000, 72.5), _t("2025-07-01", 10000, 68.0)]),
        MFHolding(scheme_name="ICICI Prudential Balanced Advantage Fund - Direct Plan - Growth", folio="DEMO-004", amc="ICICI", amfi_code="120377", plan="direct",
                  units=2100.0, nav=62.8, current_value=131880.0, invested_value=120000.0,
                  transactions=[_t("2023-06-15", 10000, 178.6), _t("2024-01-15", 10000, 166.7), _t("2024-06-15", 10000, 156.3)]),
        MFHolding(scheme_name="Axis ELSS Tax Saver Fund - Direct Plan - Growth", folio="DEMO-005", amc="Axis", amfi_code="120503", plan="direct",
                  units=520.0, nav=82.4, current_value=42848.0, invested_value=45000.0, tax_section="80C",
                  transactions=[_t("2024-02-01", 12500, 166.7), _t("2025-02-01", 12500, 156.3)]),
        MFHolding(scheme_name="HDFC Corporate Bond Fund - Direct Plan - Growth", folio="DEMO-006", amc="HDFC", amfi_code="118987", plan="direct",
                  units=3500.0, nav=29.5, current_value=103250.0, invested_value=100000.0,
                  transactions=[_t("2024-01-01", 50000, 1785.7), _t("2025-01-01", 50000, 1724.1)]),
    ]
    clear_holdings(user_id)
    try:
        holdings = enrich_holdings(holdings)
    except Exception as e:
        log.warning(f"Demo enrichment failed: {e}")
    save_holdings(holdings, user_id)
    log.info("Demo portfolio loaded")
    return JSONResponse({"status": "ok", "holdings_count": len(holdings)})


@app.post("/clear")
async def clear(request: Request):
    """Clear all stored holdings."""
    user_id = _get_user_id(request)
    clear_holdings(user_id)
    if user_id != DEMO_USER_ID:
        clear_holdings(DEMO_USER_ID)
    log.info("All holdings cleared")
    return JSONResponse({"status": "ok", "message": "All holdings cleared"})


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
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
