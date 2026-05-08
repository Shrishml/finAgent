"""Search term insurance plans based on user profile."""
import json
import logging
from pathlib import Path

log = logging.getLogger("finagent")

_DATA = Path(__file__).parent.parent / "data" / "term_insurance_plans.json"

SCHEMA = {
    "name": "search_term_insurance",
    "description": "Search term insurance plans matching user's age and cover requirement",
    "parameters": {
        "cover_amount": {"type": "int", "required": True, "description": "Desired cover in INR (e.g. 10000000 for 1Cr)"},
        "age": {"type": "int", "required": False, "description": "User's age (auto-filled from profile if available)"},
    },
    "ui_component": "comparison_table",
    "status_message": "Searching term insurance plans",
}


def _lookup_premium(table: dict, age: int, cover: int, gender: str = "M") -> int | None:
    """Find nearest premium from the static table."""
    cover_label = f"{cover // 10000000}Cr" if cover >= 10000000 else f"{cover // 100000}L"
    # Try exact match first, then nearby ages
    for a in [age, age - (age % 5), age - (age % 5) + 5]:
        key = f"{a}_{cover_label}_{gender}"
        if key in table:
            return table[key]
    return None


async def execute(params: dict, user_id: int, context: dict) -> dict:
    cover = int(params.get("cover_amount", 10000000))
    age = int(params.get("age", 0))

    # Auto-fill age from profile
    profile = context.get("profile", {})
    if not age and profile.get("age"):
        age = int(profile["age"])
    if not age:
        return {"error": "I need your age to search plans. How old are you?"}

    plans = json.loads(_DATA.read_text())
    results = []
    for plan in plans:
        if age < plan["min_age"] or age > plan["max_age"]:
            continue
        if cover < plan["min_cover"] or cover > plan["max_cover"]:
            continue
        premium = _lookup_premium(plan["premium_table"], age, cover)
        if not premium:
            continue
        results.append({
            "id": plan["id"],
            "name": plan["name"],
            "provider": plan["provider"],
            "type": "Pure Term" if plan["type"] == "term" else "Term + Return",
            "premium_monthly": premium,
            "premium_annual": premium * 12,
            "cover_amount": cover,
            "csr": plan["claim_settlement_ratio"],
            "features": plan["features"],
            "url": plan["url"],
        })

    results.sort(key=lambda x: x["premium_monthly"])

    if not results:
        return {"error": f"No plans found for age {age}, cover ₹{cover:,}. Try a different cover amount."}

    cover_label = f"₹{cover // 10000000}Cr" if cover >= 10000000 else f"₹{cover // 100000}L"
    return {
        "message": f"Found {len(results)} term insurance plans for age {age}, {cover_label} cover.",
        "ui_component": "comparison_table",
        "ui_data": {
            "title": f"Term Insurance — {cover_label} cover, age {age}",
            "items": results,
        },
    }
