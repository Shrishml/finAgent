"""API route registration."""
from fastapi import FastAPI

from finagent.api.auth import router as auth_router
from finagent.api.pages import router as pages_router
from finagent.api.chat import router as chat_router
from finagent.api.holdings import router as holdings_router
from finagent.api.goals import router as goals_router
from finagent.api.profile import router as profile_router
from finagent.api.overview import router as overview_router
from finagent.api.dev import router as dev_router
from finagent.api.admin import router as admin_router
from finagent.reddit_tool.api import router as reddit_tool_router


def register_routes(app: FastAPI):
    app.include_router(auth_router)
    app.include_router(pages_router)
    app.include_router(chat_router)
    app.include_router(holdings_router)
    app.include_router(goals_router)
    app.include_router(profile_router)
    app.include_router(overview_router)
    app.include_router(dev_router)
    app.include_router(admin_router)
    app.include_router(reddit_tool_router)
