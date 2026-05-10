"""Reddit Tool API — generate financial advice from pasted user queries."""
import hashlib
import logging
import re

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from finagent.orchestrator.engine import handle_query
from finagent.agents.onboarding import extract_profile_data, apply_extractions
from finagent.storage import (
    load_profile, save_profile, save_message, load_conversation,
)
from finagent.models.profile import UserProfile

log = logging.getLogger("finagent")
router = APIRouter(prefix="/api/reddit-tool", tags=["reddit-tool"])

_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\[(?:[0-9;]+)m')
_OPTIONS_RE = re.compile(r'\n*\[OPTIONS:.*?\]\s*$', re.DOTALL)
_ACTION_RE = re.compile(r'\[ACTION:\s*\w+\([^)]*\)\]')

REDDIT_SYSTEM_SUFFIX = """
IMPORTANT FORMATTING RULES for this response:
- Keep under 300 words, be direct and actionable
- Use Reddit markdown (**, *, numbered lists)
- No "as an AI" disclaimers — speak as a knowledgeable peer
- If you made assumptions, state them briefly at the end
- Do NOT include [OPTIONS: ...] at the end
- Do NOT include [ACTION: ...] tags — this is a read-only response, no actions should be triggered
- End with: "---\n*Ran the math on your numbers with [Arth](https://askarth.com)*"
"""


def _text_to_user_id(text: str) -> int:
    """Deterministic int user_id from input text hash."""
    h = hashlib.md5(f"reddit_anon_{text[:100]}".encode()).hexdigest()
    return int(h[:8], 16)


def _clean_reply(text: str) -> str:
    """Strip ANSI codes, [OPTIONS: ...], and [ACTION: ...] from response."""
    text = _ANSI_RE.sub('', text)
    text = _ACTION_RE.sub('', text)
    text = _OPTIONS_RE.sub('', text)
    # Clean up double newlines left by removed ACTION tags
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


class GenerateRequest(BaseModel):
    text: str


class ChatRequest(BaseModel):
    user_id: int
    message: str


@router.post("/generate")
async def generate(req: GenerateRequest):
    """Extract profile from pasted text and generate advice."""
    if not req.text.strip():
        return JSONResponse({"error": "Please paste the user's query/post"}, status_code=400)

    user_id = _text_to_user_id(req.text)

    # Create/load anonymous user profile
    profile = await load_profile(user_id)
    if not profile:
        profile = UserProfile(user_id=user_id)

    # Extract profile data from text
    extractions = await extract_profile_data(req.text, profile)
    if extractions:
        await apply_extractions(profile, extractions)
        await save_profile(profile)

    # Generate advice — prepend formatting instructions to the query
    # The orchestrator will save messages to chat_history automatically
    query = f"{REDDIT_SYSTEM_SUFFIX}\n\nUser's post:\n{req.text}"
    response = await handle_query(query, user_id=user_id)
    response = _clean_reply(response)

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

    # Load conversation but filter out system prompt messages
    conversation = await load_conversation(user_id, limit=10)
    conversation = [m for m in conversation if not m.get("content", "").startswith("\nIMPORTANT FORMATTING")]

    return JSONResponse({
        "user_id": user_id,
        "profile": profile_summary,
        "conversation": conversation,
        "reddit_reply": response,
    })


@router.post("/chat")
async def chat(req: ChatRequest):
    """Continue conversation — operator adds context or asks for changes."""
    query = f"{REDDIT_SYSTEM_SUFFIX}\n\nOperator follow-up:\n{req.message}"
    response = await handle_query(query, user_id=req.user_id)
    response = _clean_reply(response)

    conversation = await load_conversation(req.user_id, limit=10)
    conversation = [m for m in conversation if not m.get("content", "").startswith("\nIMPORTANT FORMATTING")]

    return JSONResponse({
        "response": response,
        "reddit_reply": response,
        "conversation": conversation,
    })
