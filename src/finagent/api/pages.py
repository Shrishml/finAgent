"""Page routes — HTML pages and changelog."""
import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["pages"])
_UI_DIR = Path(__file__).parent.parent.parent / "ui"


@router.get("/", response_class=HTMLResponse)
async def landing():
    f = _UI_DIR / "index.html"
    return f.read_text() if f.exists() else "<h1>FinBestie</h1>"

@router.get("/app", response_class=HTMLResponse)
@router.get("/demo", response_class=HTMLResponse)
async def dashboard():
    f = _UI_DIR / "app.html"
    return f.read_text() if f.exists() else "<h1>FinBestie</h1>"

@router.get("/about", response_class=HTMLResponse)
async def about():
    f = _UI_DIR / "about.html"
    return f.read_text() if f.exists() else "<h1>About FinBestie</h1>"

@router.get("/help/cas", response_class=HTMLResponse)
async def help_cas():
    f = _UI_DIR / "help-cas.html"
    return f.read_text() if f.exists() else "<h1>CAS Help</h1>"

@router.get("/mockup-profile", response_class=HTMLResponse)
async def mockup_profile():
    f = _UI_DIR / "mockup-profile.html"
    return f.read_text() if f.exists() else "<h1>Mockup not found</h1>"

@router.get("/changelog")
async def changelog():
    f = _UI_DIR / "changelog.json"
    return json.loads(f.read_text()) if f.exists() else []
