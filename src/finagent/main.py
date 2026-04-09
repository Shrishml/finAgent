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
from finagent.utils.returns import compute_holding_returns

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
async def index():
    index_file = _UI_DIR / "index.html"
    if index_file.exists():
        return index_file.read_text()
    return "<h1>FinAgent</h1><p>UI not found. Place index.html in src/ui/</p>"


@app.post("/upload")
async def upload(request: Request, user_id: int = Depends(require_auth), file: UploadFile = File(...), password: str = Form("")):
    """Upload a CAMS/KFintech PDF and parse it."""
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
        save_holdings(holdings, user_id)
        return JSONResponse({
            "status": "ok",
            "domain": domain,
            "holdings_count": len(holdings),
            "schemes": [h.scheme_name for h in holdings],
        })
    except Exception as e:
        log.error(f"Upload failed: {e}\n{traceback.format_exc()}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=400)
    finally:
        tmp_path.unlink(missing_ok=True)


@app.post("/chat")
async def chat(request: Request, query: str = Form(...)):
    """Chat endpoint — classify intent and route to agent."""
    user_id = _get_user_id(request)
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

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/holdings")
async def get_holdings(request: Request):
    """Get current stored holdings summary. Triggers lazy enrichment if needed."""
    user_id = _get_user_id(request)
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
async def demo(request: Request):
    """Load a demo portfolio for users to explore without uploading."""
    user_id = _get_user_id(request)
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
async def clear(request: Request, user_id: int = Depends(require_auth)):
    """Clear all stored holdings."""
    clear_holdings(user_id)
    log.info("All holdings cleared")
    return JSONResponse({"status": "ok", "message": "All holdings cleared"})


@app.get("/suggestions")
async def suggestions(request: Request):
    """Generate personalized question suggestions based on portfolio."""
    user_id = _get_user_id(request)
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

def main():
    cfg = get_config()
    server = cfg.get("server", {})
    host = server.get("host", "0.0.0.0")
    port = server.get("port", 8000)
    print(f"🚀 FinAgent starting at http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
