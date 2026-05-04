"""Intent classifier — LLM-based routing."""
import json
import logging

from finagent.llm import get_provider
from finagent.tracing.decorators import traced_chain

log = logging.getLogger("finagent")

CLASSIFY_PROMPT = """Classify this user query about personal finance. Respond with JSON only.

{{"domain": "mf" or "insurance" or "loan" or "health_check" or "goals" or "general", "mode": "analyze" or "research" or "deep_dive" or "cross_domain"}}

Rules:
- "mf" = mutual funds, SIP, portfolio, expense ratio, NAV, XIRR, ELSS, index funds
- "insurance" = health/term/life insurance, premium, coverage, claims
- "loan" = home loan, personal loan, EMI, prepayment, interest rate
- "health_check" = financial health score, how am I doing, action plan, diagnose my finances
- "goals" = financial goals, saving for house/car/retirement/education/wedding/travel/emergency fund, target amount, goal planning
- "general" = greetings, data submission, unclear, or multi-domain questions. If the user is just providing financial data (amounts, values, balances), classify as general.
- "analyze" = questions about user's own data ("my portfolio", "my funds", "what do I have")
- "research" = searching for new options ("find me", "best fund", "recommend", "compare")
- "deep_dive" = historical analysis of a specific fund ("how did X perform", "rolling returns", "crash", "SIP simulation", "drawdown", "volatility", "consistency")
- "cross_domain" = questions spanning multiple domains ("should I prepay loan or invest")

Query: {query}"""

_FALLBACK = {"domain": "general", "mode": "analyze"}


@traced_chain("intent_classifier")
async def classify_intent(query: str) -> dict:
    """Classify user query into domain + mode using LLM."""
    llm = get_provider("default")
    try:
        raw = await llm.complete(CLASSIFY_PROMPT.format(query=query), json_mode=True)
        parsed = json.loads(raw)
        if "domain" in parsed and "mode" in parsed:
            return parsed
    except Exception as e:
        log.warning(f"[router] intent classification failed: {e}")
    return _FALLBACK
