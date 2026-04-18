"""Profile data extraction and goal creation utilities.

Formerly the onboarding state machine. Now just provides:
- extract_profile_data(): LLM-based extraction from user messages
- apply_extractions(): Apply extracted data to profile
- create_goals_from_mentions(): Create Goal records from mentioned goals
"""
import json
import logging

from finagent.llm import get_provider
from finagent.models.profile import UserProfile
from finagent.models.goal import Goal, GOAL_TEMPLATES
from finagent.storage.sqlite import load_profile, save_profile, save_goal

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


# --- Goal creation from mentions ---

_TEMPLATE_KEYWORDS = {
    "retirement": ["retire", "retirement", "early retirement"],
    "house": ["home", "house", "flat", "apartment", "property", "bangalore", "mumbai", "delhi"],
    "education": ["education", "college", "school", "child education", "kid"],
    "car": ["car", "vehicle", "bike"],
    "marriage": ["marriage", "wedding"],
    "emergency": ["emergency", "rainy day", "safety net"],
    "travel": ["travel", "vacation", "trip", "holiday"],
}


def _match_template(goal_text: str) -> str:
    g = goal_text.lower()
    for template, keywords in _TEMPLATE_KEYWORDS.items():
        if any(kw in g for kw in keywords):
            return template
    return "custom"


def create_goals_from_mentions(user_id: int, goals_mentioned: list[str]) -> list[dict]:
    """Create Goal records from goal mentions. Returns created goal data."""
    from datetime import date, timedelta
    created = []
    for text in goals_mentioned:
        template = _match_template(text)
        tmpl = GOAL_TEMPLATES[template]
        target_date = (date.today() + timedelta(days=5 * 365)).isoformat()
        goal = Goal(
            user_id=user_id,
            name=text,
            template=template,
            target_amount=tmpl["suggested_amount"],
            target_date=target_date,
        )
        goal_id = save_goal(goal)
        log.info(f"[goals] created goal: {text} → template={template}")
        created.append({
            "goal_id": goal_id,
            "name": text,
            "template": template,
            "label": tmpl.get("label", "⚙️ Custom"),
            "target_amount": tmpl["suggested_amount"],
            "target_date": target_date,
            "growth_rate": goal.growth_rate,
        })
    return created
