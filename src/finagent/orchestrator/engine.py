"""Orchestrator — routes classified intents to domain agents."""
import logging
import time
from finagent.agents.mf import MFAgent
from finagent.agents.onboarding import handle_onboarding
from finagent.orchestrator.router import classify_intent
from finagent.storage.sqlite import load_holdings, save_holdings, load_profile, get_user_name
from finagent.connectors.amfi import enrich_holdings

log = logging.getLogger("finagent")
_agents = {"mf": MFAgent()}

# Keywords that should bypass onboarding and go straight to domain agents
_BYPASS_KEYWORDS = ["my portfolio", "my funds", "show my", "upload", "holdings", "xirr", "expense ratio"]


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
        if domain == "health_check":
            return "Health score feature is coming soon! For now, I can help with mutual fund analysis."
        return f"I can help with mutual funds for now. Ask me about your portfolio, expense ratios, or fund recommendations."

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
                user_name = get_user_name(user_id)
                result = await handle_onboarding(query, user_id, user_name)
                yield result["response"]
                return

    yield "[STATUS] Analyzing your question..."
    intent = await classify_intent(query)
    domain = intent.get("domain", "general")

    agent = _agents.get(domain)
    if not agent:
        yield "I can help with mutual funds for now. Ask me about your portfolio."
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
