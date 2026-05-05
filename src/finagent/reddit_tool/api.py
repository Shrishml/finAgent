"""Reddit Tool API — generate financial advice from Reddit posts."""
import hashlib
import logging
import re

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from finagent.reddit_tool import fetch_thread
from finagent.orchestrator.engine import handle_query
from finagent.agents.onboarding import extract_profile_data, apply_extractions
from finagent.storage.sqlite import (
    load_profile, save_profile, save_message, load_conversation,
)
from finagent.models.profile import UserProfile

log = logging.getLogger("finagent")
router = APIRouter(prefix="/api/reddit-tool", tags=["reddit-tool"])

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\[(?:[0-9;]+)m')

REDDIT_SYSTEM_SUFFIX = """
Format your response for Reddit (r/IndiaInvestments):
- Keep under 300 words, be direct and actionable
- Use Reddit markdown (**, *, numbered lists)
- No "as an AI" disclaimers — speak as a knowledgeable peer
- If you made assumptions, state them briefly at the end
- End with: "---\\n*Ran the math on your numbers with [Arth](https://askarth.com)*"
"""


def _post_id_to_user_id(post_id: str) -> int:
    """Deterministic int user_id from Reddit post_id."""
    h = hashlib.md5(f"reddit_anon_{post_id}".encode()).hexdigest()
    return int(h[:8], 16)  # 32-bit int from first 8 hex chars


class GenerateRequest(BaseModel):
    url: str


class ChatRequest(BaseModel):
    user_id: int
    message: str


@router.post("/generate")
async def generate(req: GenerateRequest):
    """Fetch Reddit thread, extract profile, generate advice."""
    try:
        # 1. Fetch thread
        thread = await fetch_thread(req.url)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    except Exception as e:
        log.error(f"Reddit fetch failed: {e}")
        return JSONResponse({"error": f"Failed to fetch thread: {e}"}, status_code=502)

    post_id = thread["post_id"]
    user_id = _post_id_to_user_id(post_id)

    # 2. Build full context from OP + comments by OP
    op_author = thread["author"]
    op_comments = [c["body"] for c in thread["comments"] if c["author"] == op_author]
    full_text = f"{thread['title']}\n\n{thread['body']}"
    if op_comments:
        full_text += "\n\nAdditional context from OP's comments:\n" + "\n".join(op_comments)

    # 3. Create/load anonymous user profile
    profile = load_profile(user_id)
    if not profile:
        profile = UserProfile(user_id=user_id)

    # 4. Extract profile data from Reddit text
    extractions = await extract_profile_data(full_text, profile)
    if extractions:
        apply_extractions(profile, extractions)
        save_profile(profile)

    # 5. Save the Reddit text as first user message
    save_message(user_id, "user", full_text, metadata={"source": "reddit_tool", "reddit_url": req.url})

    # 6. Generate advice via orchestrator (reuses real pipeline)
    query = f"{REDDIT_SYSTEM_SUFFIX}\n\nUser's Reddit post:\n{full_text}"
    response = await handle_query(query, user_id=user_id)
    response = _ANSI_RE.sub('', response)

    # 7. Save assistant response
    save_message(user_id, "assistant", response, metadata={"source": "reddit_tool"})

    # Build profile summary for UI
    profile_summary = {
        k: v for k, v in {
            "age": profile.age,
            "income": profile.monthly_income,
            "expenses": profile.total_monthly_expenses or profile.monthly_expenses,
            "occupation": profile.occupation,
            "risk_tolerance": profile.risk_tolerance,
            "goals": profile.goals_mentioned,
            "location": profile.location,
        }.items() if v
    }

    return JSONResponse({
        "user_id": user_id,
        "post_id": post_id,
        "thread": {
            "title": thread["title"],
            "author": thread["author"],
            "subreddit": thread["subreddit"],
        },
        "profile": profile_summary,
        "conversation": load_conversation(user_id, limit=10),
        "reddit_reply": response,
    })


@router.post("/chat")
async def chat(req: ChatRequest):
    """Continue conversation with anonymous Reddit user (operator adds context)."""
    query = f"{REDDIT_SYSTEM_SUFFIX}\n\nOperator follow-up:\n{req.message}"
    save_message(req.user_id, "user", req.message, metadata={"source": "reddit_tool_operator"})

    response = await handle_query(query, user_id=req.user_id)
    response = _ANSI_RE.sub('', response)

    save_message(req.user_id, "assistant", response, metadata={"source": "reddit_tool"})

    return JSONResponse({
        "response": response,
        "reddit_reply": response,
        "conversation": load_conversation(req.user_id, limit=10),
    })
