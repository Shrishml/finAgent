"""Profile data extraction utilities.

Provides:
- extract_profile_data(): LLM-based extraction from user messages
- apply_extractions(): Apply extracted data to profile
"""
import json
import logging

from finagent.llm import get_provider
from finagent.models.profile import UserProfile

log = logging.getLogger("finagent")


def _fmt_inr(n: float) -> str:
    """Format number in Indian comma style: 1,10,000."""
    s = str(int(n))
    if len(s) <= 3:
        return s
    last3 = s[-3:]
    rest = s[:-3]
    parts = []
    while rest:
        parts.append(rest[-2:])
        rest = rest[:-2]
    return ",".join(reversed(parts)) + "," + last3


EXTRACTION_PROMPT = """You are FinBestie. Extract any financial data from the user's message.

CURRENT PROFILE:
{profile_json}

USER SAID: "{user_message}"

Extract into these fields (only include fields with actual data):
- monthly_income, annual_bonus, spouse_income, other_income (numbers in INR)
- monthly_expenses, rent, emis (numbers in INR)
- loans: [{{"type": "home|car|education|personal|credit_card", "principal": N, "rate": N, "emi": N, "remaining_months": N}}]
- term_cover, health_cover (sum assured in INR), health_employer_only (bool)
- age, dependents, occupation, employer, location, marital_status, kids, risk_tolerance
- tax_regime ("old"|"new"), section_80c_used
- goals_mentioned: [string descriptions of goals]

Rules:
- Convert lakhs to actual numbers (1.1 lakh = 110000, 40L = 4000000, 1Cr = 10000000)
- Only extract what's explicitly stated, don't infer

Respond as JSON: {{"extractions": {{...}}, "has_data": true/false}}"""


async def extract_profile_data(user_message: str, profile: UserProfile) -> dict:
    """Extract financial data from a user message using LLM."""
    from dataclasses import asdict
    full = asdict(profile)
    for k in ("user_id", "pillars_completed", "pillars_skipped", "onboarding_complete", "financial_snapshot"):
        full.pop(k, None)
    profile_json = json.dumps({k: v for k, v in full.items() if v}, indent=2)

    llm = get_provider("default")
    try:
        raw = await llm.complete(
            EXTRACTION_PROMPT.format(profile_json=profile_json, user_message=user_message),
            json_mode=True,
        )
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(raw)
        return result.get("extractions", {})
    except Exception as e:
        log.error(f"[extraction] failed: {e}")
        return {}


def apply_extractions(profile: UserProfile, extractions: dict) -> bool:
    """Apply extracted data to profile. Returns True if anything changed."""
    changed = False
    field_map = {
        "monthly_income", "annual_bonus", "spouse_income", "other_income",
        "monthly_expenses", "rent", "emis",
        "term_cover", "health_cover", "health_employer_only",
        "age", "dependents", "occupation", "employer", "risk_tolerance",
        "location", "marital_status", "kids",
        "tax_regime", "section_80c_used",
    }
    for key, value in extractions.items():
        if key == "loans" and isinstance(value, list):
            profile.loans = value
            changed = True
        elif key == "goals_mentioned" and isinstance(value, list):
            existing = set(profile.goals_mentioned)
            new = [g for g in value if g not in existing]
            if new:
                profile.goals_mentioned.extend(new)
                changed = True
        elif key in field_map and value is not None:
            if isinstance(value, str) and key not in ("occupation", "employer", "risk_tolerance", "tax_regime", "location", "marital_status"):
                try:
                    value = float(value.replace(",", ""))
                except ValueError:
                    continue
            old = getattr(profile, key, None)
            if old != value:
                setattr(profile, key, value)
                changed = True
    return changed
