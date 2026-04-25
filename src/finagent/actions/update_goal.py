"""Update an existing financial goal."""
import logging
from finagent.models.goal import Goal, GOAL_TEMPLATES
from finagent.storage.sqlite import load_goals, save_goal

log = logging.getLogger("finagent")

SCHEMA = {
    "name": "update_goal",
    "description": "Update an existing goal's amount, date, or name. Use instead of create_goal when a similar goal already exists.",
    "parameters": {
        "goal_id": {"type": "int", "required": True, "description": "ID of the goal to update"},
        "goal_name": {"type": "str", "required": False, "description": "New name"},
        "target_amount": {"type": "int", "required": False, "description": "New target amount in INR"},
        "target_date": {"type": "str", "required": False, "description": "New target date YYYY-MM-DD"},
    },
    "ui_component": "goal_card",
    "status_message": "Updating your goal",
}


async def execute(params: dict, user_id: int, context: dict) -> dict:
    goal_id = int(params.get("goal_id", 0))
    if not goal_id:
        return {"error": "goal_id is required"}

    goals = load_goals(user_id)
    goal = next((g for g in goals if g.id == goal_id), None)
    if not goal:
        return {"error": f"Goal #{goal_id} not found"}

    changed = []
    if "goal_name" in params and params["goal_name"] and params["goal_name"] != goal.name:
        goal.name = params["goal_name"]
        changed.append("name")
    if "target_amount" in params and params["target_amount"]:
        new_amt = int(params["target_amount"])
        if new_amt == goal.target_amount:
            log.warning(f"[action] update_goal called with same target_amount={new_amt} for goal '{goal.name}' — LLM may have echoed old value")
        else:
            goal.target_amount = new_amt
            changed.append("target_amount")
    if "target_date" in params and params["target_date"] and params["target_date"] != goal.target_date:
        goal.target_date = params["target_date"]
        changed.append("target_date")

    save_goal(goal)
    log.info(f"[action] Goal updated: {goal.name} (id={goal_id}) for user {user_id}")

    tmpl = GOAL_TEMPLATES.get(goal.template, {})
    return {
        "message": f"Goal '{goal.name}' updated — ₹{goal.target_amount:,.0f} by {goal.target_date}.",
        "ui_component": "goal_card",
        "ui_data": {
            "goal_id": goal_id,
            "name": goal.name,
            "template": goal.template,
            "label": tmpl.get("label", "⚙️ Custom"),
            "target_amount": goal.target_amount,
            "target_date": goal.target_date,
            "growth_rate": goal.growth_rate,
        },
    }
