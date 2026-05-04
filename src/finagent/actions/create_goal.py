"""Create a financial goal via chat — uses calculators for realistic targets."""
import json
import logging
from datetime import date
from finagent.models.goal import Goal, GOAL_TEMPLATES
from finagent.models.goal_calculator import calculate_goal
from finagent.storage.sqlite import save_goal, load_profile

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
    "description": (
        "Create a financial goal. For retirement: pass monthly_expenses and age (calculator computes corpus). "
        "For house/car/education/marriage: pass current_cost and years_until. "
        "For custom/travel: pass target_amount directly. "
        "The calculator uses inflation-adjusted formulas — do NOT compute target_amount yourself for standard goals."
    ),
    "parameters": {
        "goal_name": {"type": "str", "required": True, "description": "Name of the goal"},
        "target_amount": {"type": "int", "required": False, "description": "Target amount in INR (only for custom/travel goals — calculator computes for standard goals)"},
        "target_date": {"type": "str", "required": False, "description": "Target date YYYY-MM-DD (calculator sets this for standard goals)"},
        "current_cost": {"type": "int", "required": False, "description": "Current cost estimate for house/car/education/marriage"},
        "years_until": {"type": "int", "required": False, "description": "Years until the goal"},
        "retirement_age": {"type": "int", "required": False, "description": "Desired retirement age (default 60)"},
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


def _calc_from_profile(template: str, params: dict, user_id: int) -> dict | None:
    """Build calculator kwargs from params + profile, then compute."""
    profile = load_profile(user_id) if user_id and user_id > 0 else None
    age = profile.age if profile else 0
    expenses = profile.total_monthly_expenses or profile.monthly_expenses if profile else 0

    if template == "retirement":
        if not expenses or not age:
            return None
        return calculate_goal(
            "retirement",
            monthly_expenses=expenses,
            current_age=age,
            retirement_age=int(params.get("retirement_age", 60)),
        )
    elif template == "emergency":
        if not expenses:
            return None
        return calculate_goal("emergency", monthly_expenses=expenses)
    elif template in ("house", "car", "education", "marriage"):
        current_cost = params.get("current_cost")
        years_until = params.get("years_until")
        if not current_cost or not years_until:
            return None
        cost_key = "current_price" if template in ("house", "car") else "current_cost"
        kwargs = {cost_key: int(current_cost), "years_until": int(years_until)}
        if template == "house":
            kwargs["down_payment_pct"] = 0.20
        return calculate_goal(template, **kwargs)
    return None


async def execute(params: dict, user_id: int, context: dict) -> dict:
    name = params.get("goal_name", "").strip()
    if not name:
        return {"error": "Missing goal_name"}

    template = _match_template(name)

    # Try calculator first for standard goals
    calc_result = _calc_from_profile(template, params, user_id)

    if calc_result and "error" not in calc_result:
        target_amount = calc_result["target_amount"]
        target_date = calc_result.get("target_date", params.get("target_date", ""))
        breakdown = calc_result.get("breakdown")
        description = calc_result.get("description", "")
    else:
        # Fallback: use LLM-provided amount (custom/travel or missing profile data)
        target_amount = int(params.get("target_amount", 0))
        target_date = params.get("target_date", "")
        breakdown = None
        description = ""

    if target_amount <= 0:
        return {"error": "Could not calculate target. Need more info — expenses, age, or a target_amount."}

    goal = Goal(
        user_id=user_id, name=name, template=template,
        target_amount=target_amount, target_date=target_date,
        description=description,
    )
    goal_id = save_goal(goal)
    log.info(f"[action] Goal created: {name} (id={goal_id}) target=₹{target_amount:,} template={template} calculated={'yes' if calc_result else 'no'}")

    tmpl = GOAL_TEMPLATES.get(template, {})
    ui_data = {
        "goal_id": goal_id, "name": name, "template": template,
        "label": tmpl.get("label", "⚙️ Custom"),
        "target_amount": target_amount, "target_date": target_date,
        "growth_rate": goal.growth_rate, "description": description,
    }
    if breakdown:
        ui_data["breakdown"] = breakdown

    msg = f"Goal '{name}' created — ₹{target_amount:,.0f} by {target_date}."
    if description:
        msg += f"\n\n📐 {description}"
    elif breakdown:
        details = ", ".join(f"{k}: {v}" for k, v in breakdown.items())
        msg += f"\n📊 Assumptions: {details}"

    return {"message": msg, "ui_component": "goal_card", "ui_data": ui_data}
