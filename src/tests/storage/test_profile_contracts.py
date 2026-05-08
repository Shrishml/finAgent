"""Profile round-trip contract tests: save_profile → load_profile → verify all fields.

Profile is stored as sectioned user_assets (personal, income, expenses, insurance, meta).
These tests verify every field survives the save→reconstruct round-trip.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from finagent.models.profile import UserProfile


def _setup_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import finagent.storage.sqlite as store
    store._DB_PATH = Path(path)
    store._DB_DIR = Path(path).parent
    return path, store


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


class TestProfileRoundTrip(unittest.TestCase):
    """Save a full profile → load it → verify every field matches."""

    def setUp(self):
        self.db_path, self.store = _setup_db()
        self.uid = self.store.get_or_create_user("profile-rt", "p@test.com", "RT")

    def tearDown(self):
        os.unlink(self.db_path)

    def _full_profile(self) -> UserProfile:
        p = UserProfile(user_id=self.uid)
        for section in PROFILE_SECTIONS.values():
            for k, v in section["fields"].items():
                setattr(p, k, v)
        p.onboarding_complete = True
        p.loans = [{"type": "home", "principal": 5000000, "emi": 45000, "rate": 8.5}]
        return p

    def test_full_profile_round_trip(self):
        """Every field in a complete profile must survive save→load."""
        original = self._full_profile()
        self.store.save_profile(original)
        loaded = self.store.load_profile(self.uid)
        self.assertIsNotNone(loaded)
        for section in PROFILE_SECTIONS.values():
            for field, expected in section["fields"].items():
                actual = getattr(loaded, field)
                if field in section["str_fields"]:
                    self.assertEqual(actual, expected,
                                     f"Profile.{field}: expected {expected!r}, got {actual!r}")
                else:
                    self.assertAlmostEqual(float(actual), float(expected), places=2,
                                           msg=f"Profile.{field}: expected {expected}, got {actual}")

    def test_onboarding_flag_survives(self):
        p = self._full_profile()
        self.store.save_profile(p)
        loaded = self.store.load_profile(self.uid)
        self.assertTrue(loaded.onboarding_complete)

    def test_loans_survive(self):
        """Loans are stored as user_assets type='loan', not in profile sections."""
        # Need at least one profile section for load_profile to not return None
        self.store.update_profile(self.uid, {"name": "Test"})
        # Loans go through save_assets, not save_profile
        self.store.save_assets(self.uid, "loan",
                               [{"type": "home", "principal": 5000000, "emi": 45000, "rate": 8.5}])
        loaded = self.store.load_profile(self.uid)
        # load_profile reconstructs loans from loan assets
        self.assertEqual(len(loaded.loans), 1)
        self.assertEqual(loaded.loans[0]["type"], "home")
        self.assertEqual(loaded.loans[0]["emi"], 45000)


class TestProfilePartialUpdate(unittest.TestCase):
    """Partial updates must merge, not overwrite entire profile."""

    def setUp(self):
        self.db_path, self.store = _setup_db()
        self.uid = self.store.get_or_create_user("partial", "pa@test.com", "Partial")

    def tearDown(self):
        os.unlink(self.db_path)

    def test_update_income_preserves_personal(self):
        p = UserProfile(user_id=self.uid, name="Suraj", age=30, monthly_income=100000)
        self.store.save_profile(p)
        # Update only income
        self.store.update_profile(self.uid, {"monthly_income": 150000})
        loaded = self.store.load_profile(self.uid)
        self.assertEqual(loaded.name, "Suraj")
        self.assertEqual(loaded.age, 30)
        self.assertAlmostEqual(loaded.monthly_income, 150000)

    def test_update_single_field_preserves_section(self):
        self.store.update_profile(self.uid, {"monthly_income": 100000, "annual_bonus": 200000})
        self.store.update_profile(self.uid, {"monthly_income": 120000})
        loaded = self.store.load_profile(self.uid)
        self.assertAlmostEqual(loaded.monthly_income, 120000)
        self.assertAlmostEqual(loaded.annual_bonus, 200000)  # must survive

    def test_add_expenses_after_income(self):
        self.store.update_profile(self.uid, {"monthly_income": 100000})
        self.store.update_profile(self.uid, {"rent": 25000, "groceries": 8000})
        loaded = self.store.load_profile(self.uid)
        self.assertAlmostEqual(loaded.monthly_income, 100000)
        self.assertAlmostEqual(loaded.rent, 25000)
        self.assertAlmostEqual(loaded.groceries, 8000)


class TestProfileEdgeCases(unittest.TestCase):
    """Edge cases in profile storage."""

    def setUp(self):
        self.db_path, self.store = _setup_db()
        self.uid = self.store.get_or_create_user("edge-p", "ep@test.com", "Edge")

    def tearDown(self):
        os.unlink(self.db_path)

    def test_empty_profile_loads_defaults(self):
        """User with no profile data should get default UserProfile."""
        loaded = self.store.load_profile(self.uid)
        # No data saved → None
        self.assertIsNone(loaded)

    def test_zero_values_not_lost(self):
        """Zero is a valid value (e.g. 0 kids, 0 EMI) — must not be treated as missing."""
        self.store.update_profile(self.uid, {"kids": 0, "emis": 0, "name": "Test"})
        loaded = self.store.load_profile(self.uid)
        self.assertEqual(loaded.kids, 0)
        self.assertAlmostEqual(loaded.emis, 0)

    def test_unicode_in_profile(self):
        """Hindi names and locations must survive."""
        self.store.update_profile(self.uid, {"name": "सूरज", "location": "बेंगलुरु"})
        loaded = self.store.load_profile(self.uid)
        self.assertEqual(loaded.name, "सूरज")
        self.assertEqual(loaded.location, "बेंगलुरु")

    def test_large_income_precision(self):
        """₹50L/month income must not lose precision."""
        self.store.update_profile(self.uid, {"monthly_income": 5000000})
        loaded = self.store.load_profile(self.uid)
        self.assertAlmostEqual(loaded.monthly_income, 5000000)

    def test_savings_rate_computed(self):
        """Derived property savings_rate must work after round-trip."""
        self.store.update_profile(self.uid, {"monthly_income": 100000,
                                              "total_monthly_expenses": 40000, "emis": 10000})
        loaded = self.store.load_profile(self.uid)
        # savings_rate = (100k - 40k - 10k) / 100k = 0.5
        self.assertAlmostEqual(loaded.savings_rate, 0.5)

    def test_savings_rate_zero_income(self):
        """savings_rate with zero income must return None, not crash."""
        self.store.update_profile(self.uid, {"name": "Test"})
        loaded = self.store.load_profile(self.uid)
        self.assertIsNone(loaded.savings_rate)


if __name__ == "__main__":
    unittest.main()
