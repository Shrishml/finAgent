"""Orchestrator — routes classified intents to domain agents."""
from finagent.agents.mf import MFAgent
from finagent.orchestrator.router import classify_intent
from finagent.storage.sqlite import load_holdings


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

    if mode == "analyze":
        return await agent.analyze(query, holdings)
    elif mode == "research":
        return await agent.research(query)
    else:
        return await agent.analyze(query, holdings)
