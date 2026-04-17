"""Onboarding Agent — conversational financial intake via strict pillar order."""
import json
import logging

from finagent.llm import get_provider
from finagent.models.profile import UserProfile, PILLAR_ORDER
from finagent.models.goal import Goal, GOAL_TEMPLATES
from finagent.storage.sqlite import (
    load_profile, save_profile, update_profile,
    save_message, load_conversation, save_goal,
)

log = logging.getLogger("finagent")


def _fmt_inr(n: float) -> str:
    """Format number in Indian comma style: 1,10,000 not 110,000."""
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

# What each pillar needs to be considered "complete"
PILLAR_QUESTIONS = {
    "income": "What do you do for work, and what's your monthly in-hand salary? Any bonuses, RSUs, or side income?",
    "expenses": "Roughly how much do you spend per month? Rent, food, EMIs, subscriptions — everything.",
    "assets": "What investments do you have? Mutual funds, FDs, stocks, PPF, NPS, crypto, gold — anything.",
    "liabilities": "Any loans or debt? Home loan, car loan, education loan, credit card balance?",
    "insurance": "Do you have term life insurance? And health insurance beyond what your employer provides?",
    "goals": "What are you saving towards? Any big financial goals in the next 5-10 years?",
    "wrapup": "Almost done! How would you describe your risk appetite — conservative, moderate, or aggressive?",
}

SNAPSHOT_PROMPT = """You are FinBestie. The user just finished onboarding. Generate a personalized financial snapshot based on their profile.

PROFILE:
{profile_json}

RULES:
- Start with a 1-line summary of their financial position (e.g. "You're a 28-year-old in Bangalore saving 47% of your income — that's strong.")
- Then list 2-3 RED FLAGS (🔴) — things that need urgent attention. Be specific with numbers. Examples:
  - No term insurance with dependents
  - Debt-to-income ratio above 40%
  - Zero emergency fund
  - Savings rate below 20%
- Then list 1-2 BRIGHT SPOTS (✅) — things they're doing well
- End with ONE specific next step question: "Want me to help you fix [biggest gap]?"
- Use Indian number formatting (₹1,10,000)
- Keep it under 200 words — punchy, not preachy
- If data is missing for a check, skip it — don't flag missing data as a problem
- Be direct. "You have no term insurance and a kid — that's a ₹1Cr risk" not "You might want to consider insurance"
"""

WELCOME_MSG = """Hey{name}! I'm FinBestie, your personal financial advisor. I'll help you see your complete financial picture and make your money work smarter.

Let's build your profile through a quick chat — takes about 5 minutes. You can skip any section or come back to it later.

{first_question}"""

EXTRACTION_PROMPT = """You are FinBestie, a friendly Indian financial advisor onboarding a new user.

CURRENT PROFILE:
{profile_json}

PILLARS COMPLETED: {completed}
CURRENT PILLAR: {current_pillar}
CONVERSATION SO FAR:
{conversation}

USER JUST SAID: "{user_message}"

TASKS:
1. Extract any financial data from the user's message into structured fields.
2. Decide if the current pillar ("{current_pillar}") has enough data to mark complete.
3. Generate a warm, natural follow-up response.

PILLAR COMPLETION RULES:
- income: complete if monthly_income > 0
- expenses: complete if monthly_expenses > 0
- assets: complete if user confirms what they have (even "nothing" or "just some FDs")
- liabilities: complete if user confirms loans or says "no loans"/"no debt"
- insurance: complete if user confirms coverage or says "no insurance"
- goals: complete if at least one goal is mentioned
- wrapup: complete if risk_tolerance is provided (or user says "I don't know" — infer from behavior)

EXTRACTION FIELDS (only include fields with actual data):
- monthly_income, annual_bonus, spouse_income, other_income (numbers in INR)
- monthly_expenses, rent, emis (numbers in INR)
- loans: [{{"type": "home|car|education|personal|credit_card", "principal": N, "rate": N, "emi": N, "remaining_months": N}}]
- term_cover, health_cover (sum assured in INR), health_employer_only (bool)
- age, dependents, occupation, employer, location, marital_status, kids, risk_tolerance
- tax_regime ("old"|"new"), section_80c_used
- goals_mentioned: [string descriptions of goals user mentioned]

SKIP DETECTION: If user says "skip", "later", "I'll add this later", "next", "don't have" — mark pillar as skipped.

IMPORTANT:
- Convert lakhs to actual numbers (1.1 lakh = 110000, 40L = 4000000, 1Cr = 10000000)
- If user mentions info about a FUTURE pillar, extract it but stay on current pillar
- Be HONEST, not generically positive. Never say "looks great!" unless the numbers actually support it. If savings rate is low or insurance is missing, acknowledge it. A 10% savings rate is NOT great.
- Use Indian number formatting (₹1,10,000 not ₹110,000) in your response
- Keep responses concise — 2-4 sentences max
- PERSONALISE: Reference the user's previously shared data naturally. E.g. if they earn ₹1,50,000 and spend ₹80,000, mention their ₹70,000 savings when discussing goals. Don't re-ask what's already in the profile. Tailor questions to their specific situation (age, family, income level).

Respond as JSON:
{{
  "extractions": {{}},
  "pillar_complete": true/false,
  "pillar_skipped": false,
  "response": "your natural response here",
  "dashboard_updates": []
}}"""


async def handle_onboarding(user_message: str, user_id: int, user_name: str = "") -> dict:
    """Main entry point for onboarding conversation.
    
    Returns: {"response": str, "dashboard_updates": list, "onboarding_complete": bool}
    """
    profile = load_profile(user_id)
    if not profile:
        profile = UserProfile(user_id=user_id)
        save_profile(profile)

    current = profile.current_pillar

    # All 6 pillars done — enter wrapup or finish
    if current is None:
        if profile.onboarding_complete:
            return {
                "response": await _generate_snapshot(profile),
                "dashboard_updates": ["health_score"],
                "onboarding_complete": True,
            }
        # Wrapup: collect age/risk if missing, then complete
        current = "wrapup"

    # First message ever — send welcome
    conversation = load_conversation(user_id, limit=20)
    if not conversation or user_message == "__onboarding_init__":
        if user_message == "__onboarding_init__":
            # Cards done — ask LLM to generate contextual transition to next pillar
            result = await _extract_and_respond(
                "I just finished filling in my financial details via the cards.",
                profile, [], current,
            )
            response = result.get("response", PILLAR_QUESTIONS[current])
            save_message(user_id, "assistant", response, {"pillar": current, "type": "init"})
            return {"response": response, "dashboard_updates": [], "onboarding_complete": False}
        welcome = WELCOME_MSG.format(
            name=f" {user_name.split()[0]}" if user_name else "",
            first_question=PILLAR_QUESTIONS[current],
        )
        save_message(user_id, "assistant", welcome, {"pillar": current, "type": "welcome"})
        return {
            "response": welcome,
            "dashboard_updates": [],
            "onboarding_complete": False,
        }

    # Save user message
    save_message(user_id, "user", user_message, {"pillar": current})

    # LLM extraction
    result = await _extract_and_respond(user_message, profile, conversation, current)

    # Apply extractions
    if result.get("extractions"):
        _apply_extractions(profile, result["extractions"])

    # Handle pillar completion or skip
    if result.get("pillar_skipped"):
        if current not in profile.pillars_skipped:
            profile.pillars_skipped.append(current)
    elif result.get("pillar_complete"):
        if current not in profile.pillars_completed:
            profile.pillars_completed.append(current)

    # Force-complete wrapup if risk_tolerance was extracted (don't rely on LLM flag)
    if current == "wrapup" and not profile.risk_tolerance:
        # Code-side detection — don't rely solely on LLM extraction
        q = user_message.lower()
        if any(w in q for w in ["aggressive", "high risk", "high growth"]):
            profile.risk_tolerance = "aggressive"
        elif any(w in q for w in ["moderate", "balanced", "medium"]):
            profile.risk_tolerance = "moderate"
        elif any(w in q for w in ["conservative", "safe", "low risk", "safety"]):
            profile.risk_tolerance = "conservative"
    if current == "wrapup" and profile.risk_tolerance and "wrapup" not in profile.pillars_completed:
        profile.pillars_completed.append("wrapup")
    # Also complete if LLM flagged pillar_complete during wrapup
    if current == "wrapup" and result.get("pillar_complete") and "wrapup" not in profile.pillars_completed:
        profile.pillars_completed.append("wrapup")
        if not profile.risk_tolerance:
            profile.risk_tolerance = "moderate"  # default if LLM completed but code didn't detect

    # Check if all done
    if current == "wrapup" and "wrapup" in profile.pillars_completed:
        profile.onboarding_complete = True

    save_profile(profile)

    # Create Goal records when goals pillar completes
    if current == "goals" and result.get("pillar_complete") and profile.goals_mentioned:
        _create_goals_from_mentions(user_id, profile.goals_mentioned)

    response = result.get("response", "I didn't quite catch that. Could you tell me more?")

    # If wrapup just completed, append personalized snapshot after LLM's response
    if profile.onboarding_complete:
        snapshot = await _generate_snapshot(profile)
        response += f"\n\n{snapshot}"
    # If pillar just completed and there's a next one, append transition
    elif (result.get("pillar_complete") or result.get("pillar_skipped")):
        next_pillar = profile.current_pillar
        if next_pillar:
            response += f"\n\n{PILLAR_QUESTIONS[next_pillar]}"
        else:
            # All 6 pillars done, transition to wrapup
            response += f"\n\n{PILLAR_QUESTIONS['wrapup']}"

    save_message(user_id, "assistant", response, {
        "pillar": current,
        "extractions": result.get("extractions", {}),
        "pillar_complete": result.get("pillar_complete", False),
    })

    return {
        "response": response,
        "dashboard_updates": result.get("dashboard_updates", []),
        "onboarding_complete": profile.onboarding_complete,
    }


async def _extract_and_respond(
    user_message: str, profile: UserProfile, conversation: list[dict], current_pillar: str
) -> dict:
    """Use LLM to extract structured data and generate response."""
    # Build conversation string (last 10 messages)
    conv_str = "\n".join(
        f"{'User' if m['role'] == 'user' else 'FinBestie'}: {m['content']}"
        for m in conversation[-10:]
    )

    # Pass full profile so LLM can personalise based on everything collected so far
    from dataclasses import asdict
    full = asdict(profile)
    # Remove internal state fields (passed separately)
    for k in ("user_id", "pillars_completed", "pillars_skipped", "onboarding_complete"):
        full.pop(k, None)
    # Strip empty/zero/None values to keep prompt concise
    profile_json = json.dumps({k: v for k, v in full.items() if v}, indent=2)

    prompt = EXTRACTION_PROMPT.format(
        profile_json=profile_json,
        completed=", ".join(profile.pillars_completed) or "none",
        current_pillar=current_pillar,
        conversation=conv_str,
        user_message=user_message,
    )

    llm = get_provider("default")
    try:
        raw = await llm.complete(prompt, json_mode=True)
        # Parse JSON — handle markdown code blocks
        raw = raw.strip()
        log.info(f"[onboarding] raw LLM response ({len(raw)} chars): {raw[:500]}")
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        result = json.loads(raw)
        log.info(f"[onboarding] pillar={current_pillar} extractions={result.get('extractions', {})}")
        return result
    except (json.JSONDecodeError, Exception) as e:
        log.error(f"[onboarding] LLM extraction failed: {e}, raw={raw[:300] if 'raw' in dir() else 'no response'}")
        return {
            "extractions": {},
            "pillar_complete": False,
            "response": "I didn't quite understand that. Could you rephrase?",
            "dashboard_updates": [],
        }


def _apply_extractions(profile: UserProfile, extractions: dict):
    """Apply extracted data to profile, handling type conversions."""
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
        elif key == "goals_mentioned" and isinstance(value, list):
            existing = set(profile.goals_mentioned)
            profile.goals_mentioned.extend(g for g in value if g not in existing)
        elif key in field_map and value is not None:
            # Convert string numbers
            if isinstance(value, str) and key not in ("occupation", "employer", "risk_tolerance", "tax_regime", "location", "marital_status"):
                try:
                    value = float(value.replace(",", ""))
                except ValueError:
                    continue
            setattr(profile, key, value)


async def _generate_snapshot(profile: UserProfile) -> str:
    """Generate personalized financial snapshot via LLM, cache on profile."""
    if profile.financial_snapshot:
        return profile.financial_snapshot
    from dataclasses import asdict
    full = asdict(profile)
    for k in ("user_id", "pillars_completed", "pillars_skipped", "onboarding_complete", "financial_snapshot"):
        full.pop(k, None)
    profile_json = json.dumps({k: v for k, v in full.items() if v}, indent=2)
    llm = get_provider("default")
    try:
        snapshot = await llm.complete(SNAPSHOT_PROMPT.format(profile_json=profile_json))
        snapshot = snapshot.strip()
        if snapshot.startswith("```"):
            snapshot = snapshot.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    except Exception as e:
        log.error(f"Snapshot generation failed: {e}")
        snapshot = _completion_message_fallback(profile)
    profile.financial_snapshot = snapshot
    save_profile(profile)
    return snapshot


def _completion_message_fallback(profile: UserProfile) -> str:
    """Static fallback if LLM snapshot fails."""
    parts = ["Great — your financial profile is ready! Here's what I've captured:\n"]
    if profile.monthly_income > 0:
        parts.append(f"💰 Income: ₹{_fmt_inr(profile.monthly_income)}/month")
    if profile.monthly_expenses > 0:
        rate = profile.savings_rate
        parts.append(f"🛒 Expenses: ₹{_fmt_inr(profile.monthly_expenses)}/month ({rate:.0%} savings rate)" if rate else "")
    if profile.loans:
        total_emi = profile.total_emi
        parts.append(f"🏦 Loans: {len(profile.loans)} active, ₹{_fmt_inr(total_emi)}/month EMI")
    elif "liabilities" in profile.pillars_completed:
        parts.append("🏦 Loans: None — debt free! ✅")
    if profile.term_cover > 0:
        parts.append(f"🛡️ Term cover: ₹{_fmt_inr(profile.term_cover)}")
    elif "insurance" in profile.pillars_completed:
        parts.append("🛡️ Insurance: None — this needs attention 🔴")
    skipped = profile.pillars_skipped
    if skipped:
        parts.append(f"\n⏭️ Skipped: {', '.join(skipped)} — you can add these anytime from your dashboard.")
    parts.append("\n✅ **Onboarding complete!** I've set up your financial profile.\n\n👉 Head to the **Goals tab** to see your goals and fine-tune targets.")
    return "\n".join(parts)


# Template matching keywords
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
    """Match a goal description to the best template key."""
    g = goal_text.lower()
    for template, keywords in _TEMPLATE_KEYWORDS.items():
        if any(kw in g for kw in keywords):
            return template
    return "custom"


def _create_goals_from_mentions(user_id: int, goals_mentioned: list[str]):
    """Create Goal records from onboarding goal mentions."""
    from datetime import date, timedelta
    for text in goals_mentioned:
        template = _match_template(text)
        tmpl = GOAL_TEMPLATES[template]
        target_date = (date.today() + timedelta(days=5*365)).isoformat()
        goal = Goal(
            user_id=user_id,
            name=text,
            template=template,
            target_amount=tmpl["suggested_amount"],
            target_date=target_date,
        )
        save_goal(goal)
        log.info(f"[onboarding] created goal: {text} → template={template}")
