"""Orchestrator — routes classified intents to domain agents."""
from finagent.agents.mf import MFAgent
from finagent.orchestrator.router import classify_intent
from finagent.storage.sqlite import load_holdings, save_holdings
from finagent.connectors.amfi import enrich_holdings

_agents = {"mf": MFAgent()}


async def handle_query(query: str) -> str:
    """Main entry point: classify intent → route to agent → return response."""
    intent = await classify_intent(query)
    domain = intent.get("domain", "general")
    mode = intent.get("mode", "analyze")

    agent = _agents.get(domain)
    if not agent:
        return f"I can help with mutual funds for now. Ask me about your portfolio, expense ratios, or fund recommendations."

    holdings = load_holdings()

    # Lazy enrichment: if any holdings lack expense ratios, enrich and save
    if holdings and any(h.expense_ratio == 0 and h.amfi_code for h in holdings):
        try:
            holdings = enrich_holdings(holdings)
            save_holdings(holdings)
        except Exception:
            pass  # Use unenriched data

    if mode == "analyze":
        return await agent.analyze(query, holdings)
    elif mode == "research":
        return await agent.research(query)
    elif mode == "deep_dive":
        # Find the best matching fund from user's holdings
        match = _match_fund(query, holdings)
        if match:
            return await agent.deep_dive(query, match.amfi_code, match.scheme_name)
        # No match in portfolio — try to extract fund name for research-style deep dive
        return await agent.analyze(query, holdings)
    else:
        return await agent.analyze(query, holdings)


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
