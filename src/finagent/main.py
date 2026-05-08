"""FinAgent — FastAPI application."""
import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from finagent.api import register_routes
from finagent.config import get_config

# Logging setup
_LOG_DIR = Path(__file__).parent.parent / "data"
_LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(_LOG_DIR / "finagent.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("finagent")
log.setLevel(logging.DEBUG)

app = FastAPI(title="FinAgent", version="0.1.0")

_DEV_MODE = os.environ.get("DEV_MODE", "").lower() in ("1", "true")


@app.middleware("http")
async def add_coop_header(request, call_next):
    response = await call_next(request)
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
    return response


# Serve UI
_UI_DIR = Path(__file__).parent.parent / "ui"
if _UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(_UI_DIR)), name="static")

# Register all route modules
register_routes(app)


@app.post("/auth/redeem-invite")
async def redeem_invite(request: Request):
    """Redeem an invite code to get active access."""
    token = request.cookies.get("session")
    user = get_session_user(token)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)
    user_id = get_or_create_user(user["google_id"], user["email"], user["name"], user["picture"])
    body = await request.json()
    code = (body.get("code") or "").strip().upper()
    if not code:
        return JSONResponse({"error": "Missing invite code"}, status_code=400)
    if redeem_invite_code(code, user_id):
        return JSONResponse({"status": "ok", "message": "Welcome to Arth! 🎉"})
    return JSONResponse({"error": "Invalid or expired invite code"}, status_code=400)


# --- Admin endpoints (protected by ADMIN_SECRET env var) ---
import os as _os
_ADMIN_SECRET = _os.environ.get("ADMIN_SECRET", "")


def _check_admin(request: Request):
    secret = request.headers.get("X-Admin-Secret", "")
    if not _ADMIN_SECRET or secret != _ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Admin access required")


@app.get("/admin/waitlist")
async def admin_waitlist(request: Request):
    _check_admin(request)
    return JSONResponse(list_waitlist_users())


@app.post("/admin/approve")
async def admin_approve(request: Request):
    _check_admin(request)
    body = await request.json()
    uid = body.get("user_id")
    if not uid:
        return JSONResponse({"error": "user_id required"}, status_code=400)
    set_user_access_status(uid, "active")
    return JSONResponse({"status": "ok", "user_id": uid, "access": "active"})


@app.post("/admin/invite-codes")
async def admin_create_codes(request: Request):
    _check_admin(request)
    body = await request.json()
    count = body.get("count", 5)
    max_uses = body.get("max_uses", 1)
    note = body.get("note", "")
    codes = create_invite_codes(count, max_uses, note)
    return JSONResponse({"codes": codes})


@app.get("/admin/invite-codes")
async def admin_list_codes(request: Request):
    _check_admin(request)
    return JSONResponse(list_invite_codes())


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
