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
