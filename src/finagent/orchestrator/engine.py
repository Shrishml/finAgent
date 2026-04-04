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
    else:
        return await agent.analyze(query, holdings)
