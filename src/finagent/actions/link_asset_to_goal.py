"""Link a user asset to an existing goal."""
import logging
from finagent.storage.sqlite import load_goals, load_assets, save_goal

log = logging.getLogger("finagent")

SCHEMA = {
    "name": "link_asset_to_goal",
    "description": "Link a user asset (FD, gold, EPF/PPF, NPS, ESOP, real estate) to an existing goal. Use when user says things like 'my SBI FD is for emergency fund' or 'link my PPF to retirement'.",
    "parameters": {
        "goal_name": {"type": "str", "required": True, "description": "Name or keyword matching the goal"},
        "asset_type": {"type": "str", "required": True, "description": "One of: fd, gold, epf_ppf, nps, esop, realestate"},
        "match": {"type": "str", "required": False, "description": "Keyword to match specific asset (e.g. 'SBI' for FD, 'SGB' for gold)"},
        "pct": {"type": "int", "required": False, "description": "Percentage to allocate (1-100, default 100)"},
    },
    "ui_component": None,
    "status_message": "Linking asset to goal...",
}

VALID_TYPES = {"fd", "gold", "epf_ppf", "nps", "esop", "realestate"}
TYPE_ALIASES = {"pf": "epf_ppf", "epf": "epf_ppf", "ppf": "epf_ppf",
                "property": "realestate", "real_estate": "realestate",
                "fixed_deposit": "fd", "rsu": "esop"}


async def execute(params: dict, user_id: int, context: dict) -> dict:
    goal_name = params.get("goal_name", "").strip().lower()
    asset_type = params.get("asset_type", "").strip().lower()
    asset_type = TYPE_ALIASES.get(asset_type, asset_type)
    match_kw = (params.get("match") or "").strip().lower()
    pct = min(100, max(1, int(params.get("pct", 100))))

    if asset_type not in VALID_TYPES:
        return {"error": f"Unknown asset type '{asset_type}'. Use: {', '.join(sorted(VALID_TYPES))}"}

    # Find goal by fuzzy name match
    goals = load_goals(user_id)
    goal = next((g for g in goals if goal_name in g.name.lower()), None)
    if not goal:
        return {"error": f"No goal matching '{goal_name}'. Create it first with create_goal."}

    # Find asset
    items = load_assets(user_id, asset_type)
    if not items:
        return {"error": f"No {asset_type} assets found in your profile."}

    # Match specific asset if keyword provided
    if match_kw and len(items) > 1:
        matched = next((i for i in items if match_kw in str(i).lower()), items[0])
    else:
        matched = items[0]

    asset_id = matched.get("id", 0)
    link = {"asset_type": asset_type, "asset_id": asset_id, "pct": pct}

    # Check not already linked
    for lf in goal.linked_folios:
        if isinstance(lf, dict) and lf.get("asset_type") == asset_type and lf.get("asset_id") == asset_id:
            return {"message": f"This {asset_type} is already linked to '{goal.name}'."}

    goal.linked_folios.append(link)
    save_goal(goal)

    from finagent.api.goals import _asset_value
    val = _asset_value(matched)
    log.info(f"[action] Linked {asset_type} (id={asset_id}) to goal '{goal.name}' at {pct}%")
    return {"message": f"✅ Linked {asset_type} (₹{val:,.0f}) to '{goal.name}' at {pct}% allocation."}
