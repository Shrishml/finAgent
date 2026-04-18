"""Create a financial goal via chat."""
import logging
from datetime import date
from finagent.models.goal import Goal, GOAL_TEMPLATES
from finagent.storage.sqlite import save_goal

log = logging.getLogger("finagent")

# Template name matching
_TEMPLATE_KEYWORDS = {
    "retirement": ["retire", "retirement"],
    "house": ["house", "home", "flat", "apartment", "property"],
    "education": ["education", "college", "school", "study"],
    "car": ["car", "vehicle", "bike"],
    "marriage": ["marriage", "wedding"],
    "emergency": ["emergency", "rainy day"],
    "travel": ["travel", "vacation", "trip", "holiday"],
}

SCHEMA = {
    "name": "create_goal",
    "description": "Create a financial goal with target amount and timeline",
    "parameters": {
        "goal_name": {"type": "str", "required": True, "description": "Name of the goal"},
        "target_amount": {"type": "int", "required": True, "description": "Target amount in INR"},
        "target_date": {"type": "str", "required": True, "description": "Target date YYYY-MM-DD"},
    },
    "ui_component": "goal_card",
    "status_message": "Creating your goal",
}


def _match_template(name: str) -> str:
    name_lower = name.lower()
    for template, keywords in _TEMPLATE_KEYWORDS.items():
        if any(kw in name_lower for kw in keywords):
            return template
    return "custom"


async def execute(params: dict, user_id: int, context: dict) -> dict:
    name = params.get("goal_name", "").strip()
    target_amount = int(params.get("target_amount", 0))
    target_date = params.get("target_date", "")

    if not name or target_amount <= 0 or not target_date:
        return {"error": "Missing required fields: goal_name, target_amount, target_date"}

    template = _match_template(name)
    goal = Goal(
        user_id=user_id,
        name=name,
        template=template,
        target_amount=target_amount,
        target_date=target_date,
    )
    goal_id = save_goal(goal)
    log.info(f"[action] Goal created via chat: {name} (id={goal_id}) for user {user_id}")

    tmpl = GOAL_TEMPLATES.get(template, {})
    return {
        "message": f"Goal '{name}' created — ₹{target_amount:,.0f} by {target_date}.",
        "ui_component": "goal_card",
        "ui_data": {
            "goal_id": goal_id,
            "name": name,
            "template": template,
            "label": tmpl.get("label", "⚙️ Custom"),
            "target_amount": target_amount,
            "target_date": target_date,
            "growth_rate": goal.growth_rate,
        },
    }
