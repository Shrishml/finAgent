"""Orchestrator — routes classified intents to domain agents."""
import logging
import time
from finagent.agents.mf import MFAgent
from finagent.agents.onboarding import handle_onboarding
from finagent.orchestrator.router import classify_intent
from finagent.storage.sqlite import load_holdings, save_holdings, load_profile, get_user_name, load_conversation, save_message
from finagent.connectors.amfi import enrich_holdings

log = logging.getLogger("finagent")
_agents = {"mf": MFAgent()}

# Keywords that should bypass onboarding and go straight to domain agents
_BYPASS_KEYWORDS = ["my portfolio", "my funds", "show my", "upload", "holdings", "xirr", "expense ratio"]

ADVISOR_PROMPT = """You are FinBestie, a friendly Indian financial advisor. Answer the user's question using their profile data and conversation history.

USER PROFILE:
{profile_json}

RECENT CONVERSATION:
{conversation}

USER QUESTION: {query}

Rules:
- Use Indian number formatting (₹1,10,000)
- Be specific and actionable based on their actual financial data
- If the question is about goals, reference their stated goals and suggest concrete steps
- Keep response concise — 3-6 sentences
- If you don't have enough data to answer well, say what's missing"""


async def _advisor_respond(query: str, user_id: int | None) -> str:
    """Profile-aware advisor for goals, health_check, insurance, loan, and general queries."""
    from finagent.llm import get_provider
    import json

    profile = load_profile(user_id) if user_id and user_id > 0 else None
    conversation = load_conversation(user_id, limit=10) if user_id and user_id > 0 else []

    profile_data = {}
    if profile:
        profile_data = {
            "monthly_income": profile.monthly_income,
            "monthly_expenses": profile.monthly_expenses,
            "savings_rate": f"{profile.savings_rate:.0%}" if profile.savings_rate else "unknown",
            "loans": profile.loans,
            "term_cover": profile.term_cover,
            "health_cover": profile.health_cover,
            "age": profile.age,
            "risk_tolerance": profile.risk_tolerance,
            "goals": profile.goals_mentioned,
            "occupation": profile.occupation,
        }

    conv_str = "\n".join(
        f"{'User' if m['role'] == 'user' else 'FinBestie'}: {m['content']}"
        for m in conversation[-10:]
    ) or "No prior conversation"

    prompt = ADVISOR_PROMPT.format(
        profile_json=json.dumps(profile_data, indent=2),
        conversation=conv_str,
        query=query,
    )

    # Save the user message to conversation history
    if user_id and user_id > 0:
        save_message(user_id, "user", query, {"type": "advisor"})

    llm = get_provider("default")
    response = await llm.complete(prompt)

    if user_id and user_id > 0:
        save_message(user_id, "assistant", response, {"type": "advisor"})

    return response


async def handle_query(query: str, user_id: int | None = None) -> str:
    """Main entry point: classify intent → route to agent → return response."""
    t0 = time.time()
    log.info(f"[orchestrator] start query={query!r} user_id={user_id}")

    # Check if user needs onboarding (skip for demo user -1)
    if user_id and user_id > 0:
        profile = load_profile(user_id)
        if not profile or not profile.onboarding_complete:
            # Allow bypass if user explicitly asks about their portfolio
            q_lower = query.lower()
            if not any(kw in q_lower for kw in _BYPASS_KEYWORDS):
                user_name = get_user_name(user_id)
                result = await handle_onboarding(query, user_id, user_name)
                log.info(f"[orchestrator] onboarding took {time.time()-t0:.1f}s, complete={result['onboarding_complete']}")
                return result["response"]

    intent = await classify_intent(query)
    log.info(f"[orchestrator] classify_intent took {time.time()-t0:.1f}s → {intent}")
    domain = intent.get("domain", "general")
    mode = intent.get("mode", "analyze")

    agent = _agents.get(domain)
    if not agent:
        return await _advisor_respond(query, user_id)

    holdings = load_holdings(user_id)
    log.info(f"[orchestrator] loaded {len(holdings)} holdings")

    # Lazy enrichment: if any holdings lack expense ratios, enrich and save
    if holdings and any(h.expense_ratio == 0 and h.amfi_code for h in holdings):
        try:
            t1 = time.time()
            holdings = enrich_holdings(holdings)
            save_holdings(holdings, user_id)
            log.info(f"[orchestrator] enrichment took {time.time()-t1:.1f}s")
        except Exception:
            pass  # Use unenriched data

    t2 = time.time()
    log.info(f"[orchestrator] calling agent.{mode}()")

    if mode == "analyze":
        result = await agent.analyze(query, holdings)
    elif mode == "research":
        result = await agent.research(query)
    elif mode == "deep_dive":
        match = _match_fund(query, holdings)
        if match:
            result = await agent.deep_dive(query, match.amfi_code, match.scheme_name)
        else:
            result = await agent.analyze(query, holdings)
    else:
        result = await agent.analyze(query, holdings)

    log.info(f"[orchestrator] agent.{mode}() took {time.time()-t2:.1f}s, total={time.time()-t0:.1f}s")
    return result


async def handle_query_stream(query: str, user_id: int | None = None):
    """Streaming version — yields chunks as LLM generates them."""
    # Check if user needs onboarding (skip for demo user -1)
    if user_id and user_id > 0:
        profile = load_profile(user_id)
        if not profile or not profile.onboarding_complete:
            q_lower = query.lower()
            if not any(kw in q_lower for kw in _BYPASS_KEYWORDS):
                yield "[STATUS] Understanding your response..."
                user_name = get_user_name(user_id)
                # Run onboarding with keepalive pings to prevent SSE timeout
                import asyncio
                task = asyncio.create_task(handle_onboarding(query, user_id, user_name))
                while not task.done():
                    await asyncio.sleep(3)
                    if not task.done():
                        yield "[STATUS] Thinking..."
                result = task.result()
                yield result["response"]
                if result.get("onboarding_complete"):
                    yield "[ONBOARDING_COMPLETE]"
                return

    yield "[STATUS] Analyzing your question..."
    intent = await classify_intent(query)
    domain = intent.get("domain", "general")

    agent = _agents.get(domain)
    if not agent:
        yield await _advisor_respond(query, user_id)
        return

    yield "[STATUS] Loading your portfolio..."
    holdings = load_holdings(user_id)
    if holdings and any(h.expense_ratio == 0 and h.amfi_code for h in holdings):
        try:
            yield "[STATUS] Enriching fund data..."
            holdings = enrich_holdings(holdings)
            save_holdings(holdings, user_id)
        except Exception:
            pass

    yield f"[STATUS] Reviewing {len(holdings)} funds..."

    async for chunk in agent.analyze_stream(query, holdings):
        yield chunk


def _match_fund(query: str, holdings: list) -> object | None:
    """Find the holding that best matches the fund mentioned in the query."""
    q = query.lower()
    best, best_score = None, 0
    for h in holdings:
        if not h.amfi_code:
            continue
        # Score by how many words from scheme name appear in query
        words = h.scheme_name.lower().split()
        score = sum(1 for w in words if len(w) > 2 and w in q)
        if score > best_score:
            best, best_score = h, score
    return best if best_score > 0 else (holdings[0] if holdings and holdings[0].amfi_code else None)
