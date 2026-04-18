"""GENERATE_SNAPSHOT — creates or updates the user's financial snapshot."""
import json
import logging
from dataclasses import asdict

log = logging.getLogger("finagent")

SCHEMA = {
    "name": "GENERATE_SNAPSHOT",
    "description": "Generate or update the user's personalized financial snapshot. Call when profile data changes significantly or user asks for a financial review.",
    "parameters": {
        "reason": {"type": "string", "required": False, "description": "Why the snapshot is being generated (e.g. 'onboarding_complete', 'profile_updated', 'user_requested')"},
    },
    "status_message": "📊 Generating your financial snapshot",
}

SNAPSHOT_PROMPT = """You are FinBestie. Generate a personalized financial snapshot based on the user's profile.

PROFILE:
{profile_json}

{previous_snapshot}

RULES:
- Start with a 1-line summary of their financial position
- List 2-3 RED FLAGS (🔴) — things needing urgent attention, with specific numbers
- List 1-2 BRIGHT SPOTS (✅) — things they're doing well
- End with "Here's what I can help you with:" followed by 3-4 personalized bullet points based on actual gaps
- Use Indian number formatting (₹1,10,000)
- Keep it under 200 words — punchy, not preachy
- Skip checks where data is missing
- Be direct and specific with numbers"""


async def execute(params: dict, user_id: int | None, context: dict) -> dict:
    from finagent.llm import get_provider
    from finagent.storage.sqlite import load_profile, save_snapshot, get_latest_snapshot

    if not user_id or user_id <= 0:
        return {"error": "Sign in to generate your financial snapshot"}

    profile = load_profile(user_id)
    if not profile:
        return {"error": "No profile data yet — fill in your details first"}

    if not (profile.monthly_income > 0 or profile.monthly_expenses > 0 or profile.age > 0):
        return {"error": "Need at least income, expenses, or age to generate a snapshot"}

    reason = params.get("reason", "user_requested")

    # Build profile JSON (exclude internal state)
    full = asdict(profile)
    for k in ("user_id", "pillars_completed", "pillars_skipped", "onboarding_complete", "financial_snapshot"):
        full.pop(k, None)
    profile_json = json.dumps({k: v for k, v in full.items() if v}, indent=2)

    # Include previous snapshot for continuity
    prev = get_latest_snapshot(user_id)
    prev_section = ""
    if prev:
        prev_section = f"PREVIOUS SNAPSHOT (update based on what changed):\n{prev['snapshot']}"

    llm = get_provider("default")
    try:
        snapshot = await llm.complete(SNAPSHOT_PROMPT.format(
            profile_json=profile_json,
            previous_snapshot=prev_section,
        ))
        snapshot = snapshot.strip()
        if snapshot.startswith("```"):
            snapshot = snapshot.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    except Exception as e:
        log.error(f"Snapshot generation failed: {e}")
        return {"error": f"Snapshot generation failed: {e}"}

    # Persist to snapshots table
    snap_id = save_snapshot(user_id, snapshot, trigger=reason)
    # Also cache on profile for backward compat
    profile.financial_snapshot = snapshot
    from finagent.storage.sqlite import save_profile
    save_profile(profile)

    log.info(f"[snapshot] Generated snapshot #{snap_id} for user {user_id} (trigger={reason})")

    return {
        "message": f"Snapshot updated (trigger: {reason})",
        "silent": True,
    }
