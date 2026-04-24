"""Shared dependencies for API route modules."""
import logging
import os

from fastapi import HTTPException, Request

from finagent.auth import get_session_user
from finagent.storage.sqlite import get_or_create_user

log = logging.getLogger("finagent")

DEMO_USER_ID = -1

_DEV_MODE = os.environ.get("DEV_MODE", "").lower() in ("1", "true")
_DEV_TOKEN = "arth-dev"
_DEV_USER_ID: int | None = None


def _get_dev_user_id() -> int:
    global _DEV_USER_ID
    if _DEV_USER_ID is None:
        _DEV_USER_ID = get_or_create_user("dev-user", "dev@arth.local", "Dev User", "")
        log.info(f"DEV_MODE: created dev user with id={_DEV_USER_ID}")
    return _DEV_USER_ID


def get_user_id(request: Request) -> int | None:
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
    user_id = get_user_id(request)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user_id
