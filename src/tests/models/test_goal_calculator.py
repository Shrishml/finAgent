"""Tests for goal calculator — realistic target amounts."""
import pytest
from finagent.models.goal_calculator import (
    retirement, emergency_fund, education, house, car, marriage, calculate_goal,
)


class TestRetirement:
    def test_25yo_20k_expenses(self):
        """The original bug: 25yo with ₹20K expenses should NOT get ₹1Cr."""
        r = retirement(monthly_expenses=20_000, current_age=25)
        # Should be ₹4-8 Cr range, definitely not ₹1 Cr
        assert r["target_amount"] > 3_00_00_000, f"Too low: ₹{r['target_amount']:,}"
        assert r["target_amount"] < 15_00_00_000, f"Too high: ₹{r['target_amount']:,}"
        assert "2061" in r["target_date"]  # 25 + 35 = 60

    def test_30yo_50k_expenses(self):
        r = retirement(monthly_expenses=50_000, current_age=30)
        assert r["target_amount"] > 5_00_00_000
        assert "2056" in r["target_date"]

    def test_custom_retirement_age(self):
        r = retirement(monthly_expenses=30_000, current_age=25, retirement_age=55)
        assert "2056" in r["target_date"]

    def test_already_retired(self):
        r = retirement(monthly_expenses=30_000, current_age=65)
        assert r["target_amount"] == 0
        assert "error" in r

    def test_breakdown_present(self):
        r = retirement(monthly_expenses=20_000, current_age=25)
        assert "breakdown" in r
        assert r["breakdown"]["post_retirement_years"] == 25
        assert r["breakdown"]["monthly_expenses_at_retirement"] > 20_000


class TestEmergencyFund:
    def test_default_6_months(self):
        r = emergency_fund(monthly_expenses=30_000)
        assert r["target_amount"] == 180_000

    def test_custom_months(self):
        r = emergency_fund(monthly_expenses=30_000, months=12)
        assert r["target_amount"] == 360_000


class TestEducation:
    def test_10_years_out(self):
        r = education(current_cost=10_00_000, years_until=10)
        # 10L at 10% inflation for 10 years ≈ 25.9L
        assert 25_00_000 < r["target_amount"] < 27_00_000

    def test_date_set(self):
        r = education(current_cost=5_00_000, years_until=5)
        assert "2031" in r["target_date"]


class TestHouse:
    def test_down_payment(self):
        r = house(current_price=50_00_000, years_until=5)
        # 50L at 8% for 5 years ≈ 73.5L, 20% down = ~14.7L
        assert 14_00_000 < r["target_amount"] < 16_00_000
        assert r["breakdown"]["down_payment_pct"] == "20%"

    def test_future_price_in_breakdown(self):
        r = house(current_price=1_00_00_000, years_until=10)
        assert r["breakdown"]["future_price"] > 1_00_00_000


class TestCar:
    def test_inflation(self):
        r = car(current_price=10_00_000, years_until=3)
        # 10L at 5% for 3 years ≈ 11.6L
        assert 11_00_000 < r["target_amount"] < 12_00_000


class TestMarriage:
    def test_inflation(self):
        r = marriage(current_cost=15_00_000, years_until=5)
        # 15L at 7% for 5 years ≈ 21L
        assert 20_00_000 < r["target_amount"] < 22_00_000


class TestCalculateGoal:
    def test_known_template(self):
        r = calculate_goal("retirement", monthly_expenses=20_000, current_age=25)
        assert r is not None
        assert r["target_amount"] > 1_00_00_000

    def test_unknown_template(self):
        assert calculate_goal("travel", current_cost=100_000) is None

    def test_bad_params(self):
        assert calculate_goal("retirement") is None  # missing required args


class TestTransparencyDescription:
    """Every calculator must return a human-readable description with step-by-step math."""

    @pytest.mark.parametrize("template,kwargs", [
        ("retirement", {"monthly_expenses": 20_000, "current_age": 25}),
        ("emergency", {"monthly_expenses": 30_000}),
        ("education", {"current_cost": 10_00_000, "years_until": 10}),
        ("house", {"current_price": 50_00_000, "years_until": 5}),
        ("car", {"current_price": 10_00_000, "years_until": 3}),
        ("marriage", {"current_cost": 15_00_000, "years_until": 5}),
    ])
    def test_description_present_and_nonempty(self, template, kwargs):
        r = calculate_goal(template, **kwargs)
        assert r is not None
        assert "description" in r
        assert len(r["description"]) > 50, "Description too short to be useful"

    @pytest.mark.parametrize("template,kwargs,expected_terms", [
        ("retirement", {"monthly_expenses": 20_000, "current_age": 25},
         ["inflation", "expenses", "retirement"]),
        ("emergency", {"monthly_expenses": 30_000},
         ["expenses", "months"]),
        ("house", {"current_price": 50_00_000, "years_until": 5},
         ["price", "inflation", "Down payment"]),
    ])
    def test_description_contains_key_terms(self, template, kwargs, expected_terms):
        r = calculate_goal(template, **kwargs)
        desc = r["description"].lower()
        for term in expected_terms:
            assert term.lower() in desc, f"Description missing '{term}'"

    def test_description_has_bullet_format(self):
        """Descriptions use • bullet points for structured display."""
        r = calculate_goal("retirement", monthly_expenses=20_000, current_age=25)
        assert "•" in r["description"]
        lines = [l for l in r["description"].split("\n") if l.strip()]
        bullet_lines = [l for l in lines if "•" in l]
        assert len(bullet_lines) >= 3, "Need at least 3 bullet points for transparency"
