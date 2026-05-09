"""Auth routes — Google OAuth + dev mode."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from finagent.auth import create_session, get_session_user, clear_session
from finagent.storage import get_or_create_user, get_user_access_status, redeem_invite_code
from finagent.api.deps import _DEV_MODE, _DEV_TOKEN, _get_dev_user_id

log = logging.getLogger("finagent")
router = APIRouter(tags=["auth"])


@router.post("/auth/google")
async def auth_google(request: Request):
    """Exchange Google credential for a session cookie."""
    body = await request.json()
    credential = body.get("credential", "")
    if not credential:
        return JSONResponse({"error": "Missing credential"}, status_code=400)
    try:
        token, user_info = create_session(credential)
        user_id = await get_or_create_user(user_info["google_id"], user_info["email"], user_info["name"], user_info["picture"])
        resp = JSONResponse({"status": "ok", "user": {"name": user_info["name"], "email": user_info["email"], "picture": user_info["picture"]}})
        resp.set_cookie("session", token, max_age=7 * 86400, httponly=True, samesite="lax")
        return resp
    except Exception as e:
        log.error(f"Auth failed: {e}")
        return JSONResponse({"error": str(e)}, status_code=401)


@router.post("/auth/logout")
async def auth_logout(request: Request):
    token = request.cookies.get("session")
    if token:
        clear_session(token)
    resp = JSONResponse({"status": "ok"})
    resp.delete_cookie("session")
    return resp


@router.get("/auth/me")
async def auth_me(request: Request):
    """Check current session — returns user info + access status."""
    token = request.cookies.get("session")
    if not token:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    if _DEV_MODE and token == _DEV_TOKEN:
        return JSONResponse({"status": "ok", "access": "active", "user": {"name": "Dev User", "email": "dev@arth.local", "picture": ""}})
    user = get_session_user(token)
    if not user:
        return JSONResponse({"status": "unauthenticated"}, status_code=401)
    user_id = await get_or_create_user(user["google_id"], user["email"], user["name"], user["picture"])
    access = await get_user_access_status(user_id)
    return JSONResponse({"status": "ok", "access": access, "user": {"name": user["name"], "email": user["email"], "picture": user["picture"]}})


@router.post("/auth/redeem-invite")
async def redeem_invite(request: Request):
    """Redeem an invite code to get active access."""
    token = request.cookies.get("session")
    user = get_session_user(token)
    if not user:
        return JSONResponse({"error": "Not logged in"}, status_code=401)
    user_id = await get_or_create_user(user["google_id"], user["email"], user["name"], user["picture"])
    body = await request.json()
    code = (body.get("code") or "").strip().upper()
    if not code:
        return JSONResponse({"error": "Missing invite code"}, status_code=400)
    if await redeem_invite_code(code, user_id):
        return JSONResponse({"status": "ok", "message": "Welcome to Arth! 🎉"})
    return JSONResponse({"error": "Invalid or expired invite code"}, status_code=400)
