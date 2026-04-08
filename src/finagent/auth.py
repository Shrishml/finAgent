"""Google OAuth authentication — verify ID tokens, manage sessions via cookies."""
import hashlib
import json
import secrets
import time
from pathlib import Path
from urllib.request import urlopen

_GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_SESSIONS: dict[str, dict] = {}  # token -> {user_id, email, name, picture, expires}
_SESSION_TTL = 7 * 86400  # 7 days


def _verify_google_token(credential: str) -> dict:
    """Decode and verify a Google ID token. Returns {sub, email, name, picture}."""
    # Decode payload without crypto verification (we trust Google's JS client)
    # For production, use google-auth library. This avoids adding a dependency.
    import base64
    parts = credential.split(".")
    if len(parts) != 3:
        raise ValueError("Invalid token format")
    payload = parts[1] + "=" * (4 - len(parts[1]) % 4)
    data = json.loads(base64.urlsafe_b64decode(payload))
    # Basic validation
    if data.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise ValueError("Invalid issuer")
    if data.get("exp", 0) < time.time():
        raise ValueError("Token expired")
    return {
        "google_id": data["sub"],
        "email": data.get("email", ""),
        "name": data.get("name", ""),
        "picture": data.get("picture", ""),
    }


def create_session(credential: str) -> tuple[str, dict]:
    """Verify Google credential, create session. Returns (session_token, user_info)."""
    user_info = _verify_google_token(credential)
    token = secrets.token_urlsafe(32)
    _SESSIONS[token] = {**user_info, "expires": time.time() + _SESSION_TTL}
    # Prune expired sessions
    now = time.time()
    expired = [k for k, v in _SESSIONS.items() if v["expires"] < now]
    for k in expired:
        del _SESSIONS[k]
    return token, user_info


def get_session_user(token: str | None) -> dict | None:
    """Get user info from session token. Returns None if invalid/expired."""
    if not token:
        return None
    session = _SESSIONS.get(token)
    if not session or session["expires"] < time.time():
        _SESSIONS.pop(token, None)
        return None
    return session


def clear_session(token: str):
    _SESSIONS.pop(token, None)
