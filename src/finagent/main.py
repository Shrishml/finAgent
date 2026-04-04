"""FinAgent — FastAPI application."""
import logging
import tempfile
import traceback
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from finagent.config import get_config
from finagent.connectors.base import ConnectorRegistry
from finagent.connectors.cams import CAMSConnector
from finagent.orchestrator.engine import handle_query
from finagent.storage.sqlite import save_holdings, load_holdings

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


@app.get("/", response_class=HTMLResponse)
async def index():
    index_file = _UI_DIR / "index.html"
    if index_file.exists():
        return index_file.read_text()
    return "<h1>FinAgent</h1><p>UI not found. Place index.html in src/ui/</p>"


@app.post("/upload")
async def upload(file: UploadFile = File(...), password: str = Form("")):
    """Upload a CAMS/KFintech PDF and parse it."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        domain, holdings = _registry.parse(tmp_path, password)
        save_holdings(holdings)
        log.info(f"Parsed {len(holdings)} holdings from {file.filename}")
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
async def chat(query: str = Form(...)):
    """Chat endpoint — classify intent and route to agent."""
    try:
        response = await handle_query(query)
        return JSONResponse({"status": "ok", "response": response})
    except Exception as e:
        log.error(f"Chat failed: {e}\n{traceback.format_exc()}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@app.get("/holdings")
async def get_holdings():
    """Get current stored holdings summary."""
    holdings = load_holdings()
    return JSONResponse({
        "count": len(holdings),
        "holdings": [
            {"scheme": h.scheme_name, "folio": h.folio, "value": h.current_value, "plan": h.plan}
            for h in holdings
        ],
    })


def main():
    cfg = get_config()
    server = cfg.get("server", {})
    print("🚀 FinAgent starting at http://{}:{}".format(
        server.get("host", "127.0.0.1"), server.get("port", 8000)
    ))
    uvicorn.run(app, host=server.get("host", "127.0.0.1"), port=server.get("port", 8000))


if __name__ == "__main__":
    main()
