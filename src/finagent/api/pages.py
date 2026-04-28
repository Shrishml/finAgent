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
    return f.read_text() if f.exists() else "<h1>Arth</h1>"

@router.get("/landing", response_class=HTMLResponse)
async def landing_v2():
    f = _UI_DIR / "landing.html"
    return f.read_text() if f.exists() else "<h1>Arth</h1>"

@router.get("/new-landing-page", response_class=HTMLResponse)
async def landing_v3():
    f = _UI_DIR / "new-landing.html"
    return f.read_text() if f.exists() else "<h1>Arth</h1>"

@router.get("/app", response_class=HTMLResponse)
@router.get("/demo", response_class=HTMLResponse)
async def dashboard():
    f = _UI_DIR / "app.html"
    return f.read_text() if f.exists() else "<h1>Arth</h1>"

@router.get("/about", response_class=HTMLResponse)
async def about():
    f = _UI_DIR / "about.html"
    return f.read_text() if f.exists() else "<h1>About Arth</h1>"

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

@router.get("/blogs/{slug}", response_class=HTMLResponse)
async def blog_article(slug: str):
    articles = json.loads((_UI_DIR / "blogs.json").read_text()) if (_UI_DIR / "blogs.json").exists() else {}
    article = articles.get(slug)
    if not article:
        return HTMLResponse("<h1>Article not found</h1>", status_code=404)
    tpl = (_UI_DIR / "blog-template.html").read_text()
    return tpl.replace("{{TITLE}}", article["title"]).replace("{{IMAGE}}", article["image"]).replace("{{READ_TIME}}", article["read_time"]).replace("{{BODY}}", article["body"])
