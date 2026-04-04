"""Intent classifier + deterministic router."""
import json

from finagent.llm import get_provider

INTENT_SCHEMA = {
    "domain": "mf | insurance | loan | general",
    "mode": "analyze | research | cross_domain",
}

CLASSIFY_PROMPT = """Classify this user query about personal finance. Respond with JSON only.

{{"domain": "mf" or "insurance" or "loan" or "general", "mode": "analyze" or "research" or "cross_domain"}}

Rules:
- "mf" = mutual funds, SIP, portfolio, expense ratio, NAV, XIRR, ELSS, index funds
- "insurance" = health/term/life insurance, premium, coverage, claims
- "loan" = home loan, personal loan, EMI, prepayment, interest rate
- "general" = greetings, unclear, or multi-domain questions
- "analyze" = questions about user's own data ("my portfolio", "my funds", "what do I have")
- "research" = searching for new options ("find me", "best fund", "recommend", "compare")
- "cross_domain" = questions spanning multiple domains ("should I prepay loan or invest")

Query: {query}"""


async def classify_intent(query: str) -> dict:
    """Classify user query into domain + mode. Returns dict with 'domain' and 'mode'."""
    llm = get_provider("default")
    try:
        raw = await llm.complete(CLASSIFY_PROMPT.format(query=query), json_mode=True)
        result = json.loads(raw)
        if "domain" in result and "mode" in result:
            return result
    except (json.JSONDecodeError, Exception):
        pass

    # Fallback: keyword-based classification
    return _keyword_classify(query)


def _keyword_classify(query: str) -> dict:
    """Fast fallback when LLM classification fails."""
    q = query.lower()

    # Domain detection
    domain = "general"
    mf_keywords = ["fund", "sip", "portfolio", "expense ratio", "nav", "xirr", "elss", "mutual", "nifty", "index"]
    insurance_keywords = ["insurance", "premium", "coverage", "claim", "policy", "health plan"]
    loan_keywords = ["loan", "emi", "prepay", "interest rate", "mortgage"]

    if any(k in q for k in mf_keywords):
        domain = "mf"
    elif any(k in q for k in insurance_keywords):
        domain = "insurance"
    elif any(k in q for k in loan_keywords):
        domain = "loan"

    # Mode detection
    mode = "analyze"
    if any(k in q for k in ["find", "best", "recommend", "compare", "suggest", "search", "alternative"]):
        mode = "research"
    elif any(k in q for k in ["should i", "versus", "vs", "or invest", "or prepay"]):
        mode = "cross_domain"

    return {"domain": domain, "mode": mode}
