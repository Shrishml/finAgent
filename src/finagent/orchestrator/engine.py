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
    load_mf_assets, reconcile_and_save, load_profile, save_profile,
    load_conversation, save_message, get_latest_snapshot, save_snapshot,
    load_assets, load_goals, save_goal,
)
from finagent.connectors.amfi import enrich_holdings
from finagent.actions import ACTION_REGISTRY, get_tools_prompt
from finagent.freshness import get_confidence, freshness_label, get_stale_fields

log = logging.getLogger("finagent")
_mf_agent = MFAgent()

# Regex to find [ACTION: name(param=value, ...)] in LLM output
_ACTION_RE = re.compile(r'\[ACTION:\s*(\w+)\(([^)]*)\)\]')


def _build_profile_context(profile, user_id: int) -> tuple[str, str]:
    """Build profile JSON and missing-fields hint for the prompt."""
    if not profile:
        return "{}", "No profile data yet. Ask the user about their financial situation."

    # Compute derived fields
    income = profile.monthly_income
    expenses = profile.total_monthly_expenses or profile.monthly_expenses
    emis = profile.emis
    total_outflow = expenses + emis
    surplus = income - total_outflow if income else 0

    data = {
        "name": profile.name or None,
        "age": profile.age or None,
        "occupation": profile.occupation or None,
        "location": profile.location or None,
        "marital_status": profile.marital_status or None,
        "kids": profile.kids or None,
        "risk_tolerance": profile.risk_tolerance or None,
        "monthly_income": income or None,
        "monthly_expenses": expenses or None,
        "monthly_emis": emis or None,
        "monthly_surplus": surplus if income else None,
        "savings_rate": f"{profile.savings_rate:.0%}" if profile.savings_rate else None,
        "monthly_sip": profile.monthly_sip or None,
        "annual_bonus": profile.annual_bonus or None,
        "annual_rsu": profile.annual_rsu or None,
        "spouse_income": profile.spouse_income or None,
        "other_income": profile.other_income or None,
        "term_cover": profile.term_cover or None,
        "health_cover": profile.health_cover or None,
        "loans": profile.loans or None,
        "goals": profile.goals_mentioned or None,
    }
    # Append structured assets (FDs, ESOP, gold, etc.) — skip flat sections already above
    FLAT_TYPES = {"personal", "income", "expenses", "meta"}
    assets = load_assets(user_id) if user_id and user_id > 0 else []

    # Compute freshness before mutating the list
    stale = get_stale_fields(assets, threshold=0.5) if assets else []
    stale_sections = [s for s in stale if s["asset_type"] != "meta"]

    if assets:
        by_type = {}
        for a in assets:
            t = a.pop("asset_type", "other")
            a.pop("id", None)
            updated_at = a.pop("updated_at", None)
            if t in FLAT_TYPES:
                continue
            conf = get_confidence(t, updated_at)
            a["_freshness"] = freshness_label(conf)
            by_type.setdefault(t, []).append(a)
        if by_type:
            data["assets"] = by_type

    # Inject saved goals so LLM sees existing goals before creating new ones
    goals = load_goals(user_id) if user_id and user_id > 0 else []
    if goals:
        data["existing_goals"] = [
            {"id": g.id, "name": g.name, "template": g.template,
             "target_amount": g.target_amount, "target_date": g.target_date}
            for g in goals
        ]

    profile_json = json.dumps({k: v for k, v in data.items() if v}, separators=(',', ':'))

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

    if stale_sections:
        stale_names = ", ".join(s["asset_type"] for s in stale_sections)
        hint += f"\nSTALE DATA (confirm before using in advice): {stale_names}. When advising on these topics, ask the user if the data is still current."

    return profile_json, hint


AGENT_PROMPT = """You are Arth, a friendly Indian financial advisor. You have a continuous relationship with this user — remember their context and build on it.

USER PROFILE:
{profile_json}

{snapshot_section}
PROFILE STATUS: {profile_hint}

RECENT CONVERSATION:
{conversation}

USER: {query}

RULES:
- CRITICAL — Indian number parsing: ₹7,20,00,000 = 7.2 Crore = 72000000. Indian format groups as L,LL,LL,LLL from right. ALWAYS convert to plain integers before passing to any action. Double-check: if user says "X Cr", multiply by 10000000. If user says "X lakh/L", multiply by 100000. When in doubt, count the digits.
- Use Indian number formatting (₹1,10,000)
- Be specific and actionable based on their actual data
- Reference their goals, income, and situation naturally
- For short answers (yes/no, quick tips): keep it to 2-3 sentences
- For detailed advice or analysis: use markdown formatting — **bold** for key points, bullet lists for multiple items, ### subheadings to separate sections. Make it scannable, not a wall of text
- If data is missing for a good answer, mention what would help (but don't block on it)
- When the user shares financial data (income, expenses, goals, etc.), acknowledge it naturally — extraction happens automatically
- When the user is sharing data and you need more details, just ask the clarifying questions. Do NOT give advisory analysis in the same response — wait until you have the full picture before advising
- When calling collect_profile_data: include ALL data mentioned by the user in prefill (don't leave out fields you heard). If data spans multiple card types (e.g. PPF + NPS), call multiple actions. Your text response MUST be 1-2 sentences only — no tables, no analysis, no advice. Just "Got it, I've captured your details" or "Please verify and save"
- Annual RSU/stock vesting amounts are saved automatically as income. Use collect_profile_data(esop) only for ESOP *holdings* (company, vested value, unvested value) — not for annual vesting amounts
- Before creating a goal, check existing_goals in the profile. If a goal with the same template or similar name exists, use update_goal(goal_id=...) to update it instead of creating a duplicate. IMPORTANT: when the user revises a goal's amount or date (e.g. "actually it's 1.5 Cr"), ALWAYS use update_goal with the existing goal's id — never create_goal
- For standard goals (retirement, house, car, education, marriage), do NOT compute target_amount yourself — the calculator does it using inflation-adjusted formulas. Pass the right inputs: retirement needs age+expenses (from profile), house/car/education/marriage need current_cost+years_until. Only pass target_amount for custom/travel goals
- When showing a calculated goal, explain the assumptions briefly (inflation rate, post-retirement years, etc.) so the user understands the number
- NEVER say "your onboarding is complete" or reference any onboarding process
- If STALE DATA is listed in PROFILE STATUS, confirm those values with the user before basing advice on them. Example: "Your income was ₹1.2L when we last spoke — is that still accurate?" Keep it natural, not interrogative
- At the end of your response, suggest 2-3 natural follow-up options the user might want. Format: [OPTIONS: option1 | option2 | option3]. Keep each option under 8 words. Skip for simple yes/no acknowledgments.{tools_prompt}"""

# Regex to extract [OPTIONS: ...] from LLM output
_OPTIONS_RE = re.compile(r'\[OPTIONS:\s*(.+?)\]')

# Normalize Indian-format numbers so LLM sees plain integers
_INR_NUM_RE = re.compile(r'₹\s*([\d,]+(?:\.\d+)?)')

def _normalize_indian_numbers(text: str) -> str:
    """Convert ₹7,20,00,000 → ₹72000000 so LLM doesn't misparse Indian grouping."""
    def _replace(m):
        num_str = m.group(1).replace(",", "")
        try:
            val = int(float(num_str))
            return f"₹{val}"
        except ValueError:
            return m.group(0)
    return _INR_NUM_RE.sub(_replace, text)


def _extraction_hint(extractions: dict) -> str:
    """Build a hint string from numeric extractions so advisor uses exact values."""
    nums = {k: v for k, v in extractions.items() if isinstance(v, (int, float)) and v > 0}
    if not nums:
        return ""
    parts = ", ".join(f"{k}=₹{int(v)}" for k, v in nums.items())
    return f"\nEXTRACTED NUMBERS (use these exact values, do NOT re-parse from user message): {parts}"


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


def _maybe_suggest_emergency_fund(user_id: int, profile):
    """Auto-create a suggested emergency fund goal if none exists."""
    goals = load_goals(user_id)
    if any(g.template == "emergency" for g in goals):
        return  # already has one (active or suggested)
    target = round(profile.total_monthly_expenses * 6)
    if target <= 0:
        return
    from finagent.models.goal import Goal
    goal = Goal(
        user_id=user_id, name="Emergency Fund", template="emergency",
        target_amount=target, target_date="", status="suggested",
        growth_rate=0,  # auto-fills from template
    )
    gid = save_goal(goal)
    log.info(f"[orchestrator] auto-suggested emergency fund goal id={gid} target={target}")


async def _maybe_extract_and_update(query: str, user_id: int | None, profile) -> tuple[bool, dict]:
    """Try to extract profile data from the user's message. Returns (changed, extractions)."""
    if not user_id or user_id <= 0 or not profile:
        return False, {}
    # Skip extraction for very short or clearly non-data messages
    if len(query) < 10 or query.startswith("/") or query == "__onboarding_init__":
        return False, {}

    extractions = await extract_profile_data(query, profile)
    if not extractions:
        log.debug("[orchestrator] extraction: no data found in message")
        return False, {}

    changed = apply_extractions(profile, extractions)
    if changed:
        save_profile(profile)
        log.info(f"[orchestrator] extracted and saved: {list(extractions.keys())}")
        # Auto-create suggested emergency fund goal when expenses become available
        if profile.total_monthly_expenses > 0 and user_id and user_id > 0:
            _maybe_suggest_emergency_fund(user_id, profile)
    else:
        log.debug(f"[orchestrator] extraction found {list(extractions.keys())} but no changes")

    return changed, extractions


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

    skip_extraction = query == "__onboarding_init__"
    if skip_extraction:
        query = "I just filled in my financial details. What are your initial thoughts? What should I focus on?"

    profile = load_profile(user_id) if user_id and user_id > 0 else None
    if not profile and user_id and user_id > 0:
        from finagent.models.profile import UserProfile
        profile = UserProfile(user_id=user_id)
        save_profile(profile)

    # Continuous extraction — skip for onboarding init (data already saved from cards)
    profile_changed, extractions = (False, {}) if skip_extraction else await _maybe_extract_and_update(query, user_id, profile)
    await _maybe_update_snapshot(user_id, profile, profile_changed)

    # Route MF-specific queries to specialized agent
    intent = await classify_intent(query)
    log.info(f"[orchestrator] intent={intent} ({time.time()-t0:.1f}s)")

    if _is_mf_query(query, intent):
        holdings = load_mf_assets(user_id)
        if holdings:
            if any(h.expense_ratio == 0 and h.amfi_code for h in holdings):
                try:
                    holdings = enrich_holdings(holdings)
                    reconcile_and_save(user_id, "mf", holdings, source_detail="cas_upload")
                except Exception:
                    pass
            if intent["mode"] == "deep_dive":
                match = _match_fund(query, holdings)
                if match:
                    return await _mf_agent.deep_dive(query, match.amfi_code, match.scheme_name)
            return await _mf_agent.analyze(query, holdings)

    # Everything else → profile-aware advisor
    return await _advisor_respond(query, user_id, profile, extractions)


async def handle_query_stream(query: str, user_id: int | None = None):
    """Streaming version of the single agent loop."""
    t0 = time.time()
    log.debug(f"[orchestrator] stream start query={query!r} user_id={user_id}")

    skip_extraction = query == "__onboarding_init__"
    if skip_extraction:
        query = "I just filled in my financial details. What are your initial thoughts? What should I focus on?"

    profile = load_profile(user_id) if user_id and user_id > 0 else None
    if not profile and user_id and user_id > 0:
        from finagent.models.profile import UserProfile
        profile = UserProfile(user_id=user_id)
        save_profile(profile)
        log.debug("[orchestrator] created new empty profile")

    # Continuous extraction — skip for onboarding init (data already saved from cards)
    profile_changed, extractions = (False, {}) if skip_extraction else await _maybe_extract_and_update(query, user_id, profile)
    log.debug(f"[orchestrator] extraction done profile_changed={profile_changed} ({time.time()-t0:.1f}s)")
    await _maybe_update_snapshot(user_id, profile, profile_changed)

    # Route MF queries to specialized agent
    yield "[STATUS] Analyzing your question..."
    intent = await classify_intent(query)
    log.debug(f"[orchestrator] intent={intent} ({time.time()-t0:.1f}s)")

    if _is_mf_query(query, intent):
        log.debug("[orchestrator] routing to MF agent")
        holdings = load_mf_assets(user_id)
        if holdings:
            if any(h.expense_ratio == 0 and h.amfi_code for h in holdings):
                try:
                    yield "[STATUS] Enriching fund data..."
                    holdings = enrich_holdings(holdings)
                    reconcile_and_save(user_id, "mf", holdings, source_detail="cas_upload")
                except Exception:
                    pass
            yield f"[STATUS] Reviewing {len(holdings)} funds..."
            async for chunk in _mf_agent.analyze_stream(query, holdings):
                yield chunk
            return

    # Everything else → streaming advisor with action chaining
    log.debug(f"[orchestrator] routing to advisor ({time.time()-t0:.1f}s)")
    async for chunk in _advisor_respond_stream(query, user_id, profile, extractions):
        yield chunk


async def _advisor_respond(query: str, user_id: int | None, profile=None, extractions: dict | None = None) -> str:
    """Profile-state-driven advisor."""
    from finagent.llm import get_provider

    if not profile:
        profile = load_profile(user_id) if user_id and user_id > 0 else None
    conversation = load_conversation(user_id, limit=10) if user_id and user_id > 0 else []

    profile_json, profile_hint = _build_profile_context(profile, user_id)
    conv_str = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Arth'}: {m['content']}"
        for m in conversation[-10:]
    ) or "No prior conversation"

    snapshot = get_latest_snapshot(user_id) if user_id and user_id > 0 else None
    snapshot_section = f"LAST FINANCIAL SNAPSHOT:\n{snapshot['snapshot']}\n" if snapshot else ""

    ext_hint = _extraction_hint(extractions or {})
    prompt = AGENT_PROMPT.format(
        profile_json=profile_json,
        snapshot_section=snapshot_section,
        profile_hint=profile_hint + ext_hint,
        conversation=conv_str,
        query=_normalize_indian_numbers(query),
        tools_prompt=get_tools_prompt(),
    )

    if user_id and user_id > 0:
        save_message(user_id, "user", query, {"type": "advisor"})

    llm = get_provider("default")
    response = await llm.complete(prompt)

    if user_id and user_id > 0:
        save_message(user_id, "assistant", response, {"type": "advisor"})

    return response


async def _advisor_respond_stream(query: str, user_id: int | None, profile=None, extractions: dict | None = None):
    """Streaming advisor with action chaining (max 3 rounds)."""
    from finagent.llm import get_provider

    if not profile:
        profile = load_profile(user_id) if user_id and user_id > 0 else None
    conversation = load_conversation(user_id, limit=10) if user_id and user_id > 0 else []

    profile_json, profile_hint = _build_profile_context(profile, user_id)
    ext_hint = _extraction_hint(extractions or {})
    profile_hint += ext_hint
    conv_str = "\n".join(
        f"{'User' if m['role'] == 'user' else 'Arth'}: {m['content']}"
        for m in conversation[-10:]
    ) or "No prior conversation"

    if user_id and user_id > 0:
        save_message(user_id, "user", query, {"type": "advisor"})

    snapshot = get_latest_snapshot(user_id) if user_id and user_id > 0 else None
    snapshot_section = f"LAST FINANCIAL SNAPSHOT:\n{snapshot['snapshot']}\n" if snapshot else ""

    llm = get_provider("default")
    all_clean_text = ""
    log.debug(f"[advisor] context built: profile_hint={profile_hint!r} snapshot={'yes' if snapshot else 'no'} conv_len={len(conversation)} provider={llm.__class__.__name__}")

    # Round 1: stream main response, collect actions
    prompt = AGENT_PROMPT.format(
        profile_json=profile_json,
        snapshot_section=snapshot_section,
        profile_hint=profile_hint,
        conversation=conv_str,
        query=_normalize_indian_numbers(query),
        tools_prompt=get_tools_prompt(),
    )

    full_response = ""
    streamed_up_to = 0
    async for chunk in llm.complete_stream(prompt):
        full_response += chunk
        # Don't stream anything once we detect an action block starting
        if "[ACTION:" in full_response:
            continue
        # Stream up to the last sentence boundary to avoid emitting
        # optimistic text that immediately precedes an action block.
        # Hold back the current partial sentence.
        safe = full_response.rfind(". ", streamed_up_to)
        if safe > streamed_up_to:
            yield full_response[streamed_up_to:safe + 2]
            streamed_up_to = safe + 2

    # If no actions, flush remaining text
    actions_found = list(_ACTION_RE.finditer(full_response))
    if not actions_found and streamed_up_to < len(full_response):
        yield full_response[streamed_up_to:]
    ui_components = []
    log.debug(f"[advisor] LLM done: {len(full_response)} chars, {len(actions_found)} actions found")

    if not actions_found:
        all_clean_text = full_response
    else:
        text_after = full_response[actions_found[-1].end():].strip()
        all_clean_text = _ACTION_RE.sub("", full_response).strip()

        # Execute actions, track failures and UI components
        failures = []
        retried = False
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
            log.debug(f"[advisor] executing action {action_name} params={params}")

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

        # Round 2: if actions failed, let LLM retry once with corrected params
        if failures and not retried:
            retried = True
            followup_prompt = (
                f"You just tried to help the user but some actions failed:\n"
                f"{chr(10).join(failures)}\n\n"
                f"Try again with corrected parameters. Call the tool(s) again with the right values."
            )
            followup = await llm.complete(followup_prompt)
            retry_actions = list(_ACTION_RE.finditer(followup))
            if retry_actions:
                for match in retry_actions:
                    action_name = match.group(1)
                    params = _parse_action_params(match.group(2))
                    entry = ACTION_REGISTRY.get(action_name)
                    if not entry:
                        continue
                    try:
                        result = await entry["execute"](params, user_id, {"profile": profile_json})
                        if "error" in result:
                            yield f"\n⚠️ {result['error']}"
                        else:
                            if not result.get("silent"):
                                if result.get("ui_component") and result.get("ui_data"):
                                    yield f"[ACTION:{result['ui_component']}] {json.dumps(result['ui_data'])}"
                                    ui_components.append({"type": result["ui_component"], "data": result["ui_data"]})
                                yield "[ACTION_STATUS] ✅ Done"
                    except Exception as e:
                        log.error(f"[orchestrator] Retry {action_name} failed: {e}")
                        yield f"\n⚠️ Retry failed: {e}"
            else:
                # LLM didn't produce retry actions, just show its explanation
                clean_followup = _ACTION_RE.sub("", followup).strip()
                if clean_followup:
                    yield f"\n\n{clean_followup}"
                    all_clean_text += " " + clean_followup

    # Extract and emit suggested options
    opts_match = _OPTIONS_RE.search(all_clean_text)
    if opts_match:
        options = [o.strip() for o in opts_match.group(1).split("|") if o.strip()]
        all_clean_text = _OPTIONS_RE.sub("", all_clean_text).strip()
        if options:
            log.debug(f"[advisor] suggested options: {options}")
            yield f"[OPTIONS] {json.dumps(options)}"

    if user_id and user_id > 0:
        meta = {"type": "advisor"}
        if ui_components:
            meta["actions"] = ui_components
        save_message(user_id, "assistant", all_clean_text.strip(), meta)
        log.debug(f"[advisor] saved response: {len(all_clean_text)} chars, {len(ui_components)} actions")


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
