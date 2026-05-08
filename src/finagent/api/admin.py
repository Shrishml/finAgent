"""Admin routes — waitlist management + invite codes."""
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from finagent.storage.sqlite import (
    set_user_access_status, list_waitlist_users,
    create_invite_codes, list_invite_codes,
)

router = APIRouter(prefix="/admin", tags=["admin"])
_ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "")


def _check_admin(request: Request):
    secret = request.headers.get("X-Admin-Secret", "")
    if not _ADMIN_SECRET or secret != _ADMIN_SECRET:
        raise HTTPException(status_code=403, detail="Admin access required")


@router.get("/waitlist")
async def admin_waitlist(request: Request):
    _check_admin(request)
    return JSONResponse(list_waitlist_users())


@router.post("/approve")
async def admin_approve(request: Request):
    _check_admin(request)
    body = await request.json()
    uid = body.get("user_id")
    if not uid:
        return JSONResponse({"error": "user_id required"}, status_code=400)
    set_user_access_status(uid, "active")
    return JSONResponse({"status": "ok", "user_id": uid, "access": "active"})


@router.post("/invite-codes")
async def admin_create_codes(request: Request):
    _check_admin(request)
    body = await request.json()
    codes = create_invite_codes(body.get("count", 5), body.get("max_uses", 1), body.get("note", ""))
    return JSONResponse({"codes": codes})


@router.get("/invite-codes")
async def admin_list_codes(request: Request):
    _check_admin(request)
    return JSONResponse(list_invite_codes())
