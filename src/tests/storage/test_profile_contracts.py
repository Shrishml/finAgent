"""Profile round-trip contract tests: save_profile → load_profile → verify all fields.

Profile is stored as sectioned user_assets (personal, income, expenses, insurance, meta).
These tests verify every field survives the save→reconstruct round-trip.
"""
import pytest
from finagent.models.profile import UserProfile
import finagent.storage as store


# ── Field contracts by section ──────────────────────────────────────────
PROFILE_SECTIONS = {
    "personal": {
        "fields": {"name": "Suraj", "age": 30, "occupation": "Engineer",
                    "employer": "Amazon", "location": "Bangalore",
                    "marital_status": "Married", "kids": 1,
                    "dependent_parents": "2 parents",
                    "parents_health_insurance": "no",
                    "risk_tolerance": "Moderate"},
        "str_fields": {"name", "occupation", "employer", "location",
                       "marital_status", "dependent_parents",
                       "parents_health_insurance", "risk_tolerance"},
    },
    "income": {
        "fields": {"monthly_income": 150000, "annual_bonus": 200000,
                    "spouse_income": 80000, "other_income": 5000,
                    "annual_rsu": 1000000, "monthly_sip": 30000},
        "str_fields": set(),
    },
    "expenses": {
        "fields": {"total_monthly_expenses": 60000, "rent": 25000,
                    "groceries": 8000, "utilities": 3000, "dining": 5000,
                    "annual_big_ticket": 100000, "emis": 15000},
        "str_fields": set(),
    },
    "insurance": {
        "fields": {"term_cover": 10000000, "term_premium": 12000,
                    "health_cover": 500000, "health_premium": 15000},
        "str_fields": set(),
    },
}


@pytest.fixture
async def profile_uid():
    uid = await store.get_or_create_user("profile-rt", "p@test.com", "RT")
    await store.clear_profile(uid)
    return uid


@pytest.mark.asyncio
class TestProfileRoundTrip:
    """Save a full profile → load it → verify every field matches."""

    def _full_profile(self, uid) -> UserProfile:
        p = UserProfile(user_id=uid)
        for section in PROFILE_SECTIONS.values():
            for k, v in section["fields"].items():
                setattr(p, k, v)
        p.onboarding_complete = True
        p.loans = [{"type": "home", "principal": 5000000, "emi": 45000, "rate": 8.5}]
        return p

    async def test_full_profile_round_trip(self, profile_uid):
        """Every field in a complete profile must survive save→load."""
        original = self._full_profile(profile_uid)
        await store.save_profile(original)
        loaded = await store.load_profile(profile_uid)
        assert loaded is not None
        for section in PROFILE_SECTIONS.values():
            for field, expected in section["fields"].items():
                actual = getattr(loaded, field)
                if field in section["str_fields"]:
                    assert actual == expected, f"Profile.{field}: expected {expected!r}, got {actual!r}"
                else:
                    assert abs(float(actual) - float(expected)) < 0.01, f"Profile.{field}: expected {expected}, got {actual}"

    async def test_onboarding_flag_survives(self, profile_uid):
        p = self._full_profile(profile_uid)
        await store.save_profile(p)
        loaded = await store.load_profile(profile_uid)
        assert loaded.onboarding_complete is True

    async def test_loans_survive(self, profile_uid):
        """Loans are stored as user_assets type='loan', not in profile sections."""
        # Need at least one profile section for load_profile to not return None
        await store.update_profile(profile_uid, {"name": "Test"})
        # Loans go through save_assets, not save_profile
        await store.save_assets(profile_uid, "loan",
                               [{"type": "home", "principal": 5000000, "emi": 45000, "rate": 8.5}])
        loaded = await store.load_profile(profile_uid)
        # load_profile reconstructs loans from loan assets
        assert len(loaded.loans) == 1
        assert loaded.loans[0]["type"] == "home"
        assert loaded.loans[0]["emi"] == 45000


@pytest.fixture
async def partial_uid():
    uid = await store.get_or_create_user("partial", "pa@test.com", "Partial")
    await store.clear_profile(uid)
    return uid


@pytest.mark.asyncio
class TestProfilePartialUpdate:
    """Partial updates must merge, not overwrite entire profile."""

    async def test_update_income_preserves_personal(self, partial_uid):
        p = UserProfile(user_id=partial_uid, name="Suraj", age=30, monthly_income=100000)
        await store.save_profile(p)
        # Update only income
        await store.update_profile(partial_uid, {"monthly_income": 150000})
        loaded = await store.load_profile(partial_uid)
        assert loaded.name == "Suraj"
        assert loaded.age == 30
        assert abs(loaded.monthly_income - 150000) < 0.01

    async def test_update_single_field_preserves_section(self, partial_uid):
        await store.update_profile(partial_uid, {"monthly_income": 100000, "annual_bonus": 200000})
        await store.update_profile(partial_uid, {"monthly_income": 120000})
        loaded = await store.load_profile(partial_uid)
        assert abs(loaded.monthly_income - 120000) < 0.01
        assert abs(loaded.annual_bonus - 200000) < 0.01  # must survive

    async def test_add_expenses_after_income(self, partial_uid):
        await store.update_profile(partial_uid, {"monthly_income": 100000})
        await store.update_profile(partial_uid, {"rent": 25000, "groceries": 8000})
        loaded = await store.load_profile(partial_uid)
        assert abs(loaded.monthly_income - 100000) < 0.01
        assert abs(loaded.rent - 25000) < 0.01
        assert abs(loaded.groceries - 8000) < 0.01


@pytest.fixture
async def edge_uid():
    # Use a unique user for each test to avoid state pollution
    import uuid
    unique_id = str(uuid.uuid4())[:8]
    uid = await store.get_or_create_user(f"edge-p-{unique_id}", f"ep-{unique_id}@test.com", "Edge")
    await store.clear_profile(uid)
    return uid


@pytest.mark.asyncio
class TestProfileEdgeCases:
    """Edge cases in profile storage."""

    async def test_empty_profile_loads_defaults(self, edge_uid):
        """User with no profile data should get default UserProfile."""
        loaded = await store.load_profile(edge_uid)
        # No data saved → None
        assert loaded is None

    async def test_zero_values_not_lost(self, edge_uid):
        """Zero is a valid value (e.g. 0 kids, 0 EMI) — must not be treated as missing."""
        await store.update_profile(edge_uid, {"kids": 0, "emis": 0, "name": "Test"})
        loaded = await store.load_profile(edge_uid)
        assert loaded.kids == 0
        assert abs(loaded.emis - 0) < 0.01

    async def test_unicode_in_profile(self, edge_uid):
        """Hindi names and locations must survive."""
        await store.update_profile(edge_uid, {"name": "सूरज", "location": "बेंगलुरु"})
        loaded = await store.load_profile(edge_uid)
        assert loaded.name == "सूरज"
        assert loaded.location == "बेंगलुरु"

    async def test_large_income_precision(self, edge_uid):
        """₹50L/month income must not lose precision."""
        await store.update_profile(edge_uid, {"monthly_income": 5000000})
        loaded = await store.load_profile(edge_uid)
        assert abs(loaded.monthly_income - 5000000) < 0.01

    async def test_savings_rate_computed(self, edge_uid):
        """Derived property savings_rate must work after round-trip."""
        await store.update_profile(edge_uid, {"monthly_income": 100000,
                                              "total_monthly_expenses": 40000, "emis": 10000})
        loaded = await store.load_profile(edge_uid)
        # savings_rate = (100k - 40k - 10k) / 100k = 0.5
        assert abs(loaded.savings_rate - 0.5) < 0.01

    async def test_savings_rate_zero_income(self, edge_uid):
        """savings_rate with zero income must return None, not crash."""
        await store.update_profile(edge_uid, {"name": "Test"})
        loaded = await store.load_profile(edge_uid)
        assert loaded.savings_rate is None
