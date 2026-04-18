"""Chat routes — sync, streaming, history."""
import logging
import re
import traceback

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\[(?:[0-9;]+)m')

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, StreamingResponse

from finagent.orchestrator.engine import handle_query
from finagent.storage.sqlite import load_conversation
from finagent.api.deps import get_user_id, require_auth, DEMO_USER_ID

log = logging.getLogger("finagent")
router = APIRouter(tags=["chat"])


@router.get("/chat/history")
async def chat_history(request: Request):
    """Return conversation history for the current user."""
    user_id = get_user_id(request)
    if not user_id:
        return JSONResponse({"messages": []})
    messages = load_conversation(user_id, limit=50)
    return JSONResponse({"messages": messages})


@router.post("/chat")
async def chat(request: Request, query: str = Form(...)):
    """Chat endpoint — classify intent and route to agent."""
    user_id = get_user_id(request) or DEMO_USER_ID
    log.info(f"💬 User query: {query}")
    try:
        response = await handle_query(query, user_id=user_id)
        return JSONResponse({"status": "ok", "response": _ANSI_RE.sub('', response)})
    except Exception as e:
        log.error(f"Chat failed: {e}\n{traceback.format_exc()}")
        return JSONResponse({"status": "error", "message": str(e)}, status_code=500)


@router.post("/chat/stream")
async def chat_stream(request: Request, user_id: int = Depends(require_auth), query: str = Form(...)):
    """Streaming chat endpoint — returns SSE events as LLM generates tokens."""
    from finagent.orchestrator.engine import handle_query_stream
    log.info(f"💬 [stream] User query: {query}")

    async def event_generator():
        try:
            async for chunk in handle_query_stream(query, user_id=user_id):
                yield f"data: {_ANSI_RE.sub('', chunk)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            log.error(f"Stream failed: {e}")
            yield f"data: [ERROR] {e}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
