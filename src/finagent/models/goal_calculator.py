"""Goal calculators — realistic target amounts using financial formulas.

Each calculator takes user profile data and returns a computed target_amount
plus a human-readable description explaining the math.
"""
import math
from datetime import date


# Indian defaults
DEFAULT_INFLATION = 0.07       # 7% avg India
DEFAULT_POST_RET_RETURN = 0.08 # 8% conservative post-retirement
DEFAULT_EDUCATION_INFLATION = 0.10  # education inflates faster
DEFAULT_REAL_ESTATE_INFLATION = 0.08


def _fmt(amount: float) -> str:
    """Format INR amount in lakhs/crores for readability."""
    if amount >= 1_00_00_000:
        return f"₹{amount / 1_00_00_000:.1f} Cr"
    if amount >= 1_00_000:
        return f"₹{amount / 1_00_000:.1f}L"
    return f"₹{amount:,.0f}"


def _future_value(present: float, rate: float, years: int) -> float:
    """FV = PV × (1 + r)^n"""
    return present * ((1 + rate) ** years)


def _annuity_factor(rate: float, years: int) -> float:
    """Present value annuity factor: (1 - (1+r)^-n) / r"""
    if rate == 0:
        return float(years)
    return (1 - (1 + rate) ** -years) / rate


def retirement(
    monthly_expenses: float,
    current_age: int,
    retirement_age: int = 60,
    life_expectancy: int = 85,
    inflation: float = DEFAULT_INFLATION,
    post_ret_return: float = DEFAULT_POST_RET_RETURN,
) -> dict:
    years_to_retire = retirement_age - current_age
    if years_to_retire <= 0:
        return {"target_amount": 0, "error": "Already past retirement age"}

    post_ret_years = life_expectancy - retirement_age
    annual_expenses_today = monthly_expenses * 12
    annual_at_retirement = _future_value(annual_expenses_today, inflation, years_to_retire)
    monthly_at_retirement = annual_at_retirement / 12

    real_return = (1 + post_ret_return) / (1 + inflation) - 1
    corpus = annual_at_retirement * _annuity_factor(real_return, post_ret_years)

    description = (
        f"How we calculated this:\n"
        f"• Current monthly expenses: {_fmt(monthly_expenses)}\n"
        f"• Inflation rate: {inflation:.0%} per year\n"
        f"• Years to retirement: {years_to_retire} (age {current_age} → {retirement_age})\n"
        f"• Monthly expenses at retirement: {_fmt(monthly_at_retirement)} "
        f"({_fmt(monthly_expenses)} × (1+{inflation:.0%})^{years_to_retire})\n"
        f"• Post-retirement period: {post_ret_years} years (life expectancy {life_expectancy})\n"
        f"• Post-retirement return: {post_ret_return:.0%}, real return: {real_return:.2%}\n"
        f"• Required corpus: {_fmt(corpus)} "
        f"(annual expenses × annuity factor for {post_ret_years} years)"
    )

    return {
        "target_amount": round(corpus),
        "target_date": f"{date.today().year + years_to_retire}-01-01",
        "description": description,
        "assumptions": {
            "inflation": inflation, "post_retirement_return": post_ret_return,
            "life_expectancy": life_expectancy, "retirement_age": retirement_age,
        },
        "breakdown": {
            "monthly_expenses_at_retirement": round(monthly_at_retirement),
            "post_retirement_years": post_ret_years,
            "inflation_assumed": f"{inflation:.0%}",
        },
    }


def emergency_fund(monthly_expenses: float, months: int = 6) -> dict:
    target = round(monthly_expenses * months)
    description = (
        f"How we calculated this:\n"
        f"• Monthly expenses: {_fmt(monthly_expenses)}\n"
        f"• Emergency buffer: {months} months\n"
        f"• Target: {_fmt(monthly_expenses)} × {months} = {_fmt(target)}"
    )
    return {"target_amount": target, "description": description}


def education(
    current_cost: float,
    years_until: int,
    inflation: float = DEFAULT_EDUCATION_INFLATION,
) -> dict:
    target = _future_value(current_cost, inflation, years_until)
    description = (
        f"How we calculated this:\n"
        f"• Current education cost: {_fmt(current_cost)}\n"
        f"• Education inflation: {inflation:.0%} per year\n"
        f"• Years until needed: {years_until}\n"
        f"• Future cost: {_fmt(current_cost)} × (1+{inflation:.0%})^{years_until} = {_fmt(target)}"
    )
    return {
        "target_amount": round(target),
        "target_date": f"{date.today().year + years_until}-06-01",
        "description": description,
        "assumptions": {"education_inflation": inflation},
        "breakdown": {"current_cost": current_cost, "education_inflation": f"{inflation:.0%}"},
    }


def house(
    current_price: float,
    years_until: int,
    down_payment_pct: float = 0.20,
    inflation: float = DEFAULT_REAL_ESTATE_INFLATION,
) -> dict:
    future_price = _future_value(current_price, inflation, years_until)
    target = future_price * down_payment_pct
    description = (
        f"How we calculated this:\n"
        f"• Current property price: {_fmt(current_price)}\n"
        f"• Real estate inflation: {inflation:.0%} per year\n"
        f"• Years until purchase: {years_until}\n"
        f"• Future price: {_fmt(current_price)} × (1+{inflation:.0%})^{years_until} = {_fmt(future_price)}\n"
        f"• Down payment ({down_payment_pct:.0%}): {_fmt(target)}"
    )
    return {
        "target_amount": round(target),
        "target_date": f"{date.today().year + years_until}-01-01",
        "description": description,
        "assumptions": {"real_estate_inflation": inflation, "down_payment_pct": down_payment_pct},
        "breakdown": {"future_price": round(future_price), "down_payment_pct": f"{down_payment_pct:.0%}"},
    }


def car(
    current_price: float,
    years_until: int,
    inflation: float = 0.05,
) -> dict:
    target = _future_value(current_price, inflation, years_until)
    description = (
        f"How we calculated this:\n"
        f"• Current car price: {_fmt(current_price)}\n"
        f"• Price inflation: {inflation:.0%} per year\n"
        f"• Years until purchase: {years_until}\n"
        f"• Future price: {_fmt(current_price)} × (1+{inflation:.0%})^{years_until} = {_fmt(target)}"
    )
    return {
        "target_amount": round(target),
        "target_date": f"{date.today().year + years_until}-01-01",
        "description": description,
        "assumptions": {"inflation": inflation},
    }


def marriage(
    current_cost: float,
    years_until: int,
    inflation: float = DEFAULT_INFLATION,
) -> dict:
    target = _future_value(current_cost, inflation, years_until)
    description = (
        f"How we calculated this:\n"
        f"• Current estimated cost: {_fmt(current_cost)}\n"
        f"• Inflation: {inflation:.0%} per year\n"
        f"• Years until event: {years_until}\n"
        f"• Future cost: {_fmt(current_cost)} × (1+{inflation:.0%})^{years_until} = {_fmt(target)}"
    )
    return {
        "target_amount": round(target),
        "target_date": f"{date.today().year + years_until}-01-01",
        "description": description,
        "assumptions": {"inflation": inflation},
    }


# Registry: template_name → calculator function
CALCULATORS = {
    "retirement": retirement,
    "emergency": emergency_fund,
    "education": education,
    "house": house,
    "car": car,
    "marriage": marriage,
}


def calculate_goal(template: str, **kwargs) -> dict | None:
    """Run the calculator for a goal template. Returns None if no calculator."""
    calc = CALCULATORS.get(template)
    if not calc:
        return None
    try:
        return calc(**kwargs)
    except Exception:
        return None
