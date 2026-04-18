"""Orchestrator — single agent loop with profile-state-driven reasoning."""
import json
import logging
import re
import time
from dataclasses import asdict

from finagent.agents.mf import MFAgent
from finagent.agents.onboarding import extract_profile_data, apply_extractions
from finagent.orchestrator.router import classify_intent
from finagent.storage.sqlite import (
    load_holdings, save_holdings, load_profile, save_profile,
    load_conversation, save_message, get_latest_snapshot, save_snapshot,
)
from finagent.connectors.amfi import enrich_holdings
from finagent.actions import ACTION_REGISTRY, get_tools_prompt

log = logging.getLogger("finagent")
_mf_agent = MFAgent()

# Regex to find [ACTION: name(param=value, ...)] in LLM output
_ACTION_RE = re.compile(r'\[ACTION:\s*(\w+)\(([^)]*)\)\]')


def _build_profile_context(profile, user_id: int) -> tuple[str, str]:
    """Build profile JSON and missing-fields hint for the prompt."""
    if not profile:
        return "{}", "No profile data yet. Ask the user about their financial situation."

    data = {
        "monthly_income": profile.monthly_income,
        "monthly_expenses": profile.monthly_expenses,
        "savings_rate": f"{profile.savings_rate:.0%}" if profile.savings_rate else None,
        "loans": profile.loans or None,
        "term_cover": profile.term_cover or None,
        "health_cover": profile.health_cover or None,
        "age": profile.age or None,
        "risk_tolerance": profile.risk_tolerance or None,
        "goals": profile.goals_mentioned or None,
        "occupation": profile.occupation or None,
        "location": profile.location or None,
        "dependents": profile.dependents or None,
    }
    profile_json = json.dumps({k: v for k, v in data.items() if v}, indent=2)

    # Identify gaps
    missing = []
    if not profile.monthly_income:
        missing.append("income")
    if not profile.monthly_expenses:
        missing.append("expenses")
    if not profile.age:
        missing.append("age")
    if not profile.risk_tolerance:
        missing.append("risk appetite")
    if not profile.term_cover and not profile.health_cover:
        missing.append("insurance details")
    if not profile.goals_mentioned:
        missing.append("financial goals")

    if missing:
        hint = f"Missing data: {', '.join(missing)}. Naturally weave questions about these into conversation when relevant — don't interrogate."
    else:
        hint = "Profile is complete. Focus on actionable advice."

    return profile_json, hint


AGENT_PROMPT = """You are FinBestie, a friendly Indian financial advisor. You have a continuous relationship with this user — remember their context and build on it.

USER PROFILE:
{profile_json}

{snapshot_section}
PROFILE STATUS: {profile_hint}

RECENT CONVERSATION:
{conversation}

USER: {query}

RULES:
- Use Indian number formatting (₹1,10,000)
- Be specific and actionable based on their actual data
- Reference their goals, income, and situation naturally
- Keep responses concise — 3-6 sentences
- If data is missing for a good answer, mention what would help (but don't block on it)
- When the user shares financial data (income, expenses, goals, etc.), acknowledge it naturally — extraction happens automatically
- NEVER say "your onboarding is complete" or reference any onboarding process{tools_prompt}"""


def _parse_action_params(params_str: str) -> dict:
    params = {}
    if not params_str.strip():
        return params
    for part in params_str.split(","):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            v = v.strip().strip('"').strip("'")
            try:
                v = int(v)
            except ValueError:
                try:
                    v = float(v)
                except ValueError:
                    pass
            params[k.strip()] = v
    return params


async def _maybe_extract_and_update(query: str, user_id: int | None, profile) -> bool:
    """Try to extract profile data from the user's message. Returns True if profile changed."""
    if not user_id or user_id <= 0 or not profile:
        return False
    # Skip extraction for very short or clearly non-data messages
    if len(query) < 10 or query.startswith("/") or query == "__onboarding_init__":
        return False

    extractions = await extract_profile_data(query, profile)
    if not extractions:
        return False

    changed = apply_extractions(profile, extractions)
    if changed:
        save_profile(profile)
        log.info(f"[orchestrator] extracted and saved: {list(extractions.keys())}")

    return changed


async def _maybe_update_snapshot(user_id: int, profile, profile_changed: bool):
    """Trigger snapshot update if profile changed significantly."""
    if not user_id or user_id <= 0 or not profile_changed:
        return
    # Only regenerate if we have minimum data
    has_data = (profile.monthly_income > 0 or profile.monthly_expenses > 0) and profile.age > 0
    if not has_data:
        return
    snap = get_latest_snapshot(user_id)
    if snap:
        # Don't regenerate too frequently — at most once per conversation
        return
    # First snapshot — generate it
    from finagent.actions.generate_snapshot import execute as gen_snapshot
    await gen_snapshot({"reason": "first_data"}, user_id, {})


def _is_mf_query(query: str, intent: dict) -> bool:
    """Check if this query needs the specialized MF agent."""
    return intent.get("domain") == "mf" and intent.get("mode") in ("analyze", "deep_dive")


async def handle_query(query: str, user_id: int | None = None) -> str:
    """Single agent loop: extract → route → respond."""
    t0 = time.time()
    log.info(f"[orchestrator] start query={query!r} user_id={user_id}")

    if query == "__onboarding_init__":
        query = "I just filled in my financial details. What are your initial thoughts? What should I focus on?"

    profile = load_profile(user_id) if user_id and user_id > 0 else None
    if not profile and user_id and user_id > 0:
        from finagent.models.profile import UserProfile
        profile = UserProfile(user_id=user_id)
        save_profile(profile)

    # Continuous extraction — every message might contain financial data
    profile_changed = await _maybe_extract_and_update(query, user_id, profile)
    await _maybe_update_snapshot(user_id, profile, profile_changed)

    # Route MF-specific queries to specialized agent
    intent = await classify_intent(query)
    log.info(f"[orchestrator] intent={intent} ({time.time()-t0:.1f}s)")

    if _is_mf_query(query, intent):
        holdings = load_holdings(user_id)
        if holdings:
            if any(h.expense_ratio == 0 and h.amfi_code for h in holdings):
                try:
                    holdings = enrich_holdings(holdings)
                    save_holdings(holdings, user_id)
                except Exception:
                    pass
            if intent["mode"] == "deep_dive":
                match = _match_fund(query, holdings)
                if match:
                    return await _mf_agent.deep_dive(query, match.amfi_code, match.scheme_name)
            return await _mf_agent.analyze(query, holdings)

    # Everything else → profile-aware advisor
    return await _advisor_respond(query, user_id, profile)


async def handle_query_stream(query: str, user_id: int | None = None):
    """Streaming version of the single agent loop."""
    if query == "__onboarding_init__":
        query = "I just filled in my financial details. What are your initial thoughts? What should I focus on?"

    profile = load_profile(user_id) if user_id and user_id > 0 else None
    if not profile and user_id and user_id > 0:
        from finagent.models.profile import UserProfile
        profile = UserProfile(user_id=user_id)
        save_profile(profile)

    # Continuous extraction
    profile_changed = await _maybe_extract_and_update(query, user_id, profile)
    await _maybe_update_snapshot(user_id, profile, profile_changed)

    # Route MF queries to specialized agent
    yield "[STATUS] Analyzing your question..."
    intent = await classify_intent(query)

    if _is_mf_query(query, intent):
        holdings = load_holdings(user_id)
        if holdings:
            if any(h.expense_ratio == 0 and h.amfi_code for h in holdings):
                try:
                    yield "[STATUS] Enriching fund data..."
                    holdings = enrich_holdings(holdings)
                    save_holdings(holdings, user_id)
                except Exception:
                    pass
            yield f"[STATUS] Reviewing {len(holdings)} funds..."
            async for chunk in _mf_agent.analyze_stream(query, holdings):
                yield chunk
            return

    # Everything else → streaming advisor with action chaining
    async for chunk in _advisor_respond_stream(query, user_id, profile):
        yield chunk


async def _advisor_respond(query: str, user_id: int | None, profile=None) -> str:
    """Profile-state-driven advisor."""
    from finagent.llm import get_provider

    if not profile:
        profile = load_profile(user_id) if user_id and user_id > 0 else None
    conversation = load_conversation(user_id, limit=10) if user_id and user_id > 0 else []

    profile_json, profile_hint = _build_profile_context(profile, user_id)
    conv_str = "\n".join(
        f"{'User' if m['role'] == 'user' else 'FinBestie'}: {m['content']}"
        for m in conversation[-10:]
    ) or "No prior conversation"

    snapshot = get_latest_snapshot(user_id) if user_id and user_id > 0 else None
    snapshot_section = f"LAST FINANCIAL SNAPSHOT:\n{snapshot['snapshot']}\n" if snapshot else ""

    prompt = AGENT_PROMPT.format(
        profile_json=profile_json,
        snapshot_section=snapshot_section,
        profile_hint=profile_hint,
        conversation=conv_str,
        query=query,
        tools_prompt=get_tools_prompt(),
    )

    if user_id and user_id > 0:
        save_message(user_id, "user", query, {"type": "advisor"})

    llm = get_provider("default")
    response = await llm.complete(prompt)

    if user_id and user_id > 0:
        save_message(user_id, "assistant", response, {"type": "advisor"})

    return response


async def _advisor_respond_stream(query: str, user_id: int | None, profile=None):
    """Streaming advisor with action chaining (max 3 rounds)."""
    from finagent.llm import get_provider

    if not profile:
        profile = load_profile(user_id) if user_id and user_id > 0 else None
    conversation = load_conversation(user_id, limit=10) if user_id and user_id > 0 else []

    profile_json, profile_hint = _build_profile_context(profile, user_id)
    conv_str = "\n".join(
        f"{'User' if m['role'] == 'user' else 'FinBestie'}: {m['content']}"
        for m in conversation[-10:]
    ) or "No prior conversation"

    if user_id and user_id > 0:
        save_message(user_id, "user", query, {"type": "advisor"})

    snapshot = get_latest_snapshot(user_id) if user_id and user_id > 0 else None
    snapshot_section = f"LAST FINANCIAL SNAPSHOT:\n{snapshot['snapshot']}\n" if snapshot else ""

    llm = get_provider("default")
    all_clean_text = ""

    # Round 1: stream main response, collect actions
    prompt = AGENT_PROMPT.format(
        profile_json=profile_json,
        snapshot_section=snapshot_section,
        profile_hint=profile_hint,
        conversation=conv_str,
        query=query,
        tools_prompt=get_tools_prompt(),
    )

    full_response = ""
    async for chunk in llm.complete_stream(prompt):
        full_response += chunk
        if "[ACTION:" not in full_response:
            yield chunk

    actions_found = list(_ACTION_RE.finditer(full_response))
    ui_components = []

    if not actions_found:
        all_clean_text = full_response
    else:
        text_after = full_response[actions_found[-1].end():].strip()
        all_clean_text = _ACTION_RE.sub("", full_response).strip()

        # Execute actions, track failures and UI components
        failures = []
        ui_components = []
        for match in actions_found:
            action_name = match.group(1)
            params = _parse_action_params(match.group(2))
            entry = ACTION_REGISTRY.get(action_name)
            if not entry:
                log.warning(f"[orchestrator] Unknown action: {action_name}")
                continue

            schema = entry["schema"]
            yield f"[ACTION_STATUS] {schema.get('status_message', 'Working on it')}..."

            try:
                result = await entry["execute"](params, user_id, {"profile": profile_json})
                if "error" in result:
                    yield f"\n⚠️ {result['error']}"
                    failures.append(f"{action_name}({params}): {result['error']}")
                else:
                    if not result.get("silent"):
                        if result.get("ui_component") and result.get("ui_data"):
                            yield f"[ACTION:{result['ui_component']}] {json.dumps(result['ui_data'])}"
                            ui_components.append({"type": result["ui_component"], "data": result["ui_data"]})
                        yield "[ACTION_STATUS] ✅ Done"
            except Exception as e:
                log.error(f"[orchestrator] Action {action_name} failed: {e}")
                yield f"\n⚠️ Something went wrong: {e}"
                failures.append(f"{action_name}({params}): {e}")

        if text_after:
            yield f"\n{text_after}"
            all_clean_text += " " + text_after

        # Round 2: only if actions failed, ask LLM for brief recovery
        if failures:
            followup_prompt = (
                f"You just tried to help the user but some actions failed:\n"
                f"{chr(10).join(failures)}\n\n"
                f"In 1-2 sentences, tell the user what went wrong and what you'll do differently. "
                f"Do NOT repeat your earlier advice. Do NOT call any tools."
            )
            followup = await llm.complete(followup_prompt)
            yield f"\n\n{followup}"
            all_clean_text += " " + followup

    if user_id and user_id > 0:
        meta = {"type": "advisor"}
        if ui_components:
            meta["actions"] = ui_components
        save_message(user_id, "assistant", all_clean_text.strip(), meta)


def _match_fund(query: str, holdings: list) -> object | None:
    """Find the holding that best matches the fund mentioned in the query."""
    q = query.lower()
    best, best_score = None, 0
    for h in holdings:
        if not h.amfi_code:
            continue
        words = h.scheme_name.lower().split()
        score = sum(1 for w in words if len(w) > 2 and w in q)
        if score > best_score:
            best, best_score = h, score
    return best if best_score > 0 else (holdings[0] if holdings and holdings[0].amfi_code else None)
