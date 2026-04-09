"""Intent classifier + deterministic router."""
import json

from finagent.llm import get_provider

INTENT_SCHEMA = {
    "domain": "mf | insurance | loan | general",
    "mode": "analyze | research | deep_dive | cross_domain",
}

CLASSIFY_PROMPT = """Classify this user query about personal finance. Respond with JSON only.

{{"domain": "mf" or "insurance" or "loan" or "general", "mode": "analyze" or "research" or "deep_dive" or "cross_domain"}}

Rules:
- "mf" = mutual funds, SIP, portfolio, expense ratio, NAV, XIRR, ELSS, index funds
- "insurance" = health/term/life insurance, premium, coverage, claims
- "loan" = home loan, personal loan, EMI, prepayment, interest rate
- "general" = greetings, unclear, or multi-domain questions
- "analyze" = questions about user's own data ("my portfolio", "my funds", "what do I have")
- "research" = searching for new options ("find me", "best fund", "recommend", "compare")
- "deep_dive" = historical analysis of a specific fund ("how did X perform", "rolling returns", "crash", "SIP simulation", "drawdown", "volatility", "consistency")
- "cross_domain" = questions spanning multiple domains ("should I prepay loan or invest")

Query: {query}"""


async def classify_intent(query: str) -> dict:
    """Classify user query into domain + mode. Uses fast keyword matching first,
    only falls back to LLM for ambiguous queries."""
    result = _keyword_classify(query)
    if result["domain"] != "general":
        return result

    # Only use LLM when keyword matching can't determine domain
    llm = get_provider("default")
    try:
        raw = await llm.complete(CLASSIFY_PROMPT.format(query=query), json_mode=True)
        parsed = json.loads(raw)
        if "domain" in parsed and "mode" in parsed:
            return parsed
    except (json.JSONDecodeError, Exception):
        pass

    return result


def _keyword_classify(query: str) -> dict:
    """Fast fallback when LLM classification fails."""
    q = query.lower()

    # Domain detection
    domain = "general"
    mf_keywords = ["fund", "sip", "portfolio", "expense ratio", "nav", "xirr", "elss", "mutual", "nifty",
                    "index", "replace", "switch", "direct", "regular", "holding", "scheme", "amc",
                    "debt", "equity", "flexi", "mid cap", "small cap", "large cap", "balanced",
                    "overlap", "diversif", "consolidat", "redeem", "invest"]
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
    deep_dive_keywords = ["how did", "rolling return", "crash", "covid", "drawdown", "volatility",
                          "sip simulation", "consistency", "stress test", "historical", "max drawdown",
                          "sharpe", "cagr", "2008", "gfc", "nbfc"]
    if any(k in q for k in deep_dive_keywords):
        mode = "deep_dive"
    elif any(k in q for k in ["find", "best", "recommend", "compare", "suggest", "search", "alternative"]):
        mode = "research"
    elif any(k in q for k in ["should i", "versus", "vs", "or invest", "or prepay"]):
        mode = "cross_domain"

    return {"domain": domain, "mode": mode}
