"""Data contract tests: verify every asset type survives the full round-trip.

Extract → save_assets → load_assets → verify all fields present with correct types.
These catch silent data loss, type corruption, and field renaming bugs.
"""
import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# ── Asset contracts: required fields + types per asset type ──────────────
# Each contract defines what MUST survive the round-trip.

ASSET_CONTRACTS = {
    "epf_ppf": {
        "sample": {"epf_balance": 850000, "epf_contribution": 15000,
                    "ppf_balance": 400000, "ppf_contribution": 150000},
        "required": {"epf_balance": (int, float), "ppf_balance": (int, float)},
        "numeric": ["epf_balance", "epf_contribution", "ppf_balance", "ppf_contribution"],
    },
    "nps": {
        "sample": {"nps_balance": 200000, "nps_contribution": 5000},
        "required": {"nps_balance": (int, float)},
        "numeric": ["nps_balance", "nps_contribution"],
    },
    "mf": {
        "sample": {"scheme": "PPFAS Flexi Cap Fund", "monthly_sip": 10000,
                    "current_value": 250000, "source": "declared"},
        "required": {"scheme": str},
        "numeric": ["monthly_sip", "current_value"],
    },
    "fd": {
        "sample": {"bank": "SBI", "amount": 500000, "rate": 7.1,
                    "maturity": "2027-06", "tax_saver": "no"},
        "required": {"bank": str, "amount": (int, float)},
        "numeric": ["amount", "rate"],
    },
    "gold": {
        "sample": {"type": "sgb", "value": 300000, "weight_grams": 50,
                    "amount_invested": 250000},
        "required": {"type": str},
        "numeric": ["value", "weight_grams", "amount_invested"],
    },
    "realestate": {
        "sample": {"type": "self_occupied", "location": "Bangalore",
                    "current_value": 8000000, "purchase_price": 5000000,
                    "rental_income": 0},
        "required": {"type": str, "current_value": (int, float)},
        "numeric": ["current_value", "purchase_price", "rental_income"],
    },
    "esop": {
        "sample": {"company": "Amazon", "vested": 5000000,
                    "unvested": 3000000, "next_vesting": "2026-11"},
        "required": {"company": str},
        "numeric": ["vested", "unvested"],
    },
    "loan": {
        "sample": {"type": "home", "principal": 5000000, "emi": 45000,
                    "rate": 8.5, "remaining_months": 180},
        "required": {"type": str},
        "numeric": ["principal", "emi", "rate", "remaining_months"],
    },
    "insurance": {
        "sample": {"type": "term", "cover_amount": 10000000, "premium": 12000,
                    "provider": "HDFC Life"},
        "required": {"type": str, "cover_amount": (int, float)},
        "numeric": ["cover_amount", "premium"],
    },
}


def _temp_db():
    """Patch sqlite to use a temp DB."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


class TestAssetRoundTrip(unittest.TestCase):
    """For every asset type: save → load → verify all fields survive."""

    def setUp(self):
        self.db_path = _temp_db()
        # Patch DB path
        import finagent.storage.sqlite as store
        store._DB_PATH = Path(self.db_path)
        store._DB_DIR = Path(self.db_path).parent
        self.store = store
        # Create a test user
        self.uid = store.get_or_create_user("test-contract", "c@test.com", "Contract")

    def tearDown(self):
        os.unlink(self.db_path)

    def test_round_trip_all_asset_types(self):
        """Every asset type's sample data must survive save→load unchanged."""
        for asset_type, contract in ASSET_CONTRACTS.items():
            with self.subTest(asset_type=asset_type):
                sample = contract["sample"].copy()
                self.store.save_assets(self.uid, asset_type, [sample])
                loaded = self.store.load_assets(self.uid, asset_type)
                self.assertEqual(len(loaded), 1, f"{asset_type}: expected 1 row, got {len(loaded)}")
                data = loaded[0]
                for key, val in sample.items():
                    self.assertIn(key, data, f"{asset_type}: field '{key}' lost in round-trip")
                    self.assertEqual(data[key], val,
                                     f"{asset_type}.{key}: saved {val!r}, loaded {data[key]!r}")

    def test_required_fields_present(self):
        """Required fields must exist and have correct types after load."""
        for asset_type, contract in ASSET_CONTRACTS.items():
            with self.subTest(asset_type=asset_type):
                self.store.save_assets(self.uid, asset_type, [contract["sample"]])
                loaded = self.store.load_assets(self.uid, asset_type)[0]
                for field, expected_type in contract["required"].items():
                    self.assertIn(field, loaded, f"{asset_type}: required field '{field}' missing")
                    self.assertIsInstance(loaded[field], expected_type,
                                         f"{asset_type}.{field}: expected {expected_type}, got {type(loaded[field])}")

    def test_numeric_fields_are_numbers(self):
        """Numeric fields must load as int or float, not strings."""
        for asset_type, contract in ASSET_CONTRACTS.items():
            with self.subTest(asset_type=asset_type):
                self.store.save_assets(self.uid, asset_type, [contract["sample"]])
                loaded = self.store.load_assets(self.uid, asset_type)[0]
                for field in contract.get("numeric", []):
                    if field in loaded and loaded[field] is not None:
                        self.assertIsInstance(loaded[field], (int, float),
                                             f"{asset_type}.{field}: expected number, got {type(loaded[field])}")

    def test_multiple_items_per_type(self):
        """Multiple assets of same type must all survive."""
        fd1 = {"bank": "SBI", "amount": 500000, "rate": 7.1}
        fd2 = {"bank": "HDFC", "amount": 300000, "rate": 6.8}
        self.store.save_assets(self.uid, "fd", [fd1, fd2])
        loaded = self.store.load_assets(self.uid, "fd")
        self.assertEqual(len(loaded), 2)
        banks = {d["bank"] for d in loaded}
        self.assertEqual(banks, {"SBI", "HDFC"})

    def test_save_overwrites_not_appends(self):
        """save_assets replaces all items of that type, not appends."""
        self.store.save_assets(self.uid, "fd", [{"bank": "SBI", "amount": 100}])
        self.store.save_assets(self.uid, "fd", [{"bank": "HDFC", "amount": 200}])
        loaded = self.store.load_assets(self.uid, "fd")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["bank"], "HDFC")

    def test_empty_list_clears_assets(self):
        """Saving empty list should remove all assets of that type."""
        self.store.save_assets(self.uid, "gold", [{"type": "sgb", "value": 100}])
        self.store.save_assets(self.uid, "gold", [])
        loaded = self.store.load_assets(self.uid, "gold")
        self.assertEqual(len(loaded), 0)

    def test_asset_types_isolated(self):
        """Saving one asset type must not affect another."""
        self.store.save_assets(self.uid, "fd", [{"bank": "SBI", "amount": 100}])
        self.store.save_assets(self.uid, "gold", [{"type": "sgb", "value": 200}])
        self.store.save_assets(self.uid, "fd", [{"bank": "HDFC", "amount": 300}])
        gold = self.store.load_assets(self.uid, "gold")
        self.assertEqual(len(gold), 1)
        self.assertEqual(gold[0]["value"], 200)


class TestExtractionToStorage(unittest.TestCase):
    """Test that apply_extractions correctly routes data to storage."""

    def setUp(self):
        self.db_path = _temp_db()
        import finagent.storage.sqlite as store
        store._DB_PATH = Path(self.db_path)
        store._DB_DIR = Path(self.db_path).parent
        self.store = store
        self.uid = store.get_or_create_user("test-extract", "e@test.com", "Extract")

    def tearDown(self):
        os.unlink(self.db_path)

    def _profile(self):
        from finagent.models.profile import UserProfile
        return UserProfile(user_id=self.uid)

    def test_epf_extraction_saves_to_assets(self):
        from finagent.agents.onboarding import apply_extractions
        p = self._profile()
        apply_extractions(p, {"epf_balance": 850000, "epf_contribution": 15000})
        loaded = self.store.load_assets(self.uid, "epf_ppf")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["epf_balance"], 850000)
        self.assertEqual(loaded[0]["epf_contribution"], 15000)

    def test_mf_sip_extraction_saves_to_assets(self):
        from finagent.agents.onboarding import apply_extractions
        p = self._profile()
        apply_extractions(p, {"mf_sips": [
            {"scheme": "PPFAS Flexi Cap", "monthly_sip": 10000, "current_value": 250000}
        ]})
        loaded = self.store.load_assets(self.uid, "mf")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["scheme"], "PPFAS Flexi Cap")
        self.assertEqual(loaded[0]["monthly_sip"], 10000)

    def test_fd_extraction_saves_to_assets(self):
        from finagent.agents.onboarding import apply_extractions
        p = self._profile()
        apply_extractions(p, {"fds": [
            {"bank": "SBI", "amount": 500000, "rate": 7.1, "maturity": "2027-06"}
        ]})
        loaded = self.store.load_assets(self.uid, "fd")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["bank"], "SBI")
        self.assertEqual(loaded[0]["amount"], 500000)

    def test_gold_extraction_saves_to_assets(self):
        from finagent.agents.onboarding import apply_extractions
        p = self._profile()
        apply_extractions(p, {"gold": [
            {"type": "sgb", "current_value": 300000, "weight_grams": 50}
        ]})
        loaded = self.store.load_assets(self.uid, "gold")
        self.assertEqual(len(loaded), 1)
        # current_value gets normalized to value
        self.assertEqual(loaded[0].get("value", loaded[0].get("current_value")), 300000)

    def test_realestate_extraction_saves_to_assets(self):
        from finagent.agents.onboarding import apply_extractions
        p = self._profile()
        apply_extractions(p, {"real_estate": [
            {"type": "self_occupied", "location": "Bangalore",
             "current_value": 8000000, "purchase_price": 5000000}
        ]})
        loaded = self.store.load_assets(self.uid, "realestate")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["current_value"], 8000000)

    def test_esop_extraction_saves_to_assets(self):
        from finagent.agents.onboarding import apply_extractions
        p = self._profile()
        apply_extractions(p, {"esop_company": "Amazon", "esop_vested": 5000000,
                              "esop_unvested": 3000000})
        loaded = self.store.load_assets(self.uid, "esop")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["company"], "Amazon")
        self.assertEqual(loaded[0]["vested"], 5000000)

    def test_profile_fields_saved_to_profile(self):
        """Profile fields (income, expenses) go to profile, not assets."""
        from finagent.agents.onboarding import apply_extractions
        p = self._profile()
        apply_extractions(p, {"monthly_income": 150000, "age": 30, "name": "Suraj"})
        self.assertEqual(p.monthly_income, 150000)
        self.assertEqual(p.age, 30)
        self.assertEqual(p.name, "Suraj")

    def test_loan_extraction_saves_to_profile(self):
        """Loans are stored on the profile object, not in user_assets."""
        from finagent.agents.onboarding import apply_extractions
        p = self._profile()
        apply_extractions(p, {"loans": [
            {"type": "home", "principal": 5000000, "emi": 45000, "rate": 8.5}
        ]})
        self.assertEqual(len(p.loans), 1)
        self.assertEqual(p.loans[0]["type"], "home")
        self.assertEqual(p.loans[0]["principal"], 5000000)

    def test_update_existing_asset_merges(self):
        """Second extraction for same asset type should merge, not duplicate."""
        from finagent.agents.onboarding import apply_extractions
        p = self._profile()
        apply_extractions(p, {"epf_balance": 500000})
        apply_extractions(p, {"epf_contribution": 15000})
        loaded = self.store.load_assets(self.uid, "epf_ppf")
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["epf_balance"], 500000)
        self.assertEqual(loaded[0]["epf_contribution"], 15000)

    def test_pending_items_not_saved(self):
        """Incomplete mentions (pending) should NOT create asset rows."""
        from finagent.agents.onboarding import apply_extractions
        p = self._profile()
        apply_extractions(p, {"mf_sips": [{"scheme": "ICICI Small Cap"}],
                              "_pending": ["ICICI Small Cap: no amount provided"]})
        loaded = self.store.load_assets(self.uid, "mf")
        # Should not save MF with only scheme name and no data
        self.assertEqual(len(loaded), 0)


class TestDataCorruptionGuards(unittest.TestCase):
    """Test that bad data doesn't silently corrupt storage."""

    def setUp(self):
        self.db_path = _temp_db()
        import finagent.storage.sqlite as store
        store._DB_PATH = Path(self.db_path)
        store._DB_DIR = Path(self.db_path).parent
        self.store = store
        self.uid = store.get_or_create_user("test-corrupt", "x@test.com", "Corrupt")

    def tearDown(self):
        os.unlink(self.db_path)

    def test_none_values_handled(self):
        """None values in data should not cause load failures."""
        self.store.save_assets(self.uid, "fd", [{"bank": "SBI", "amount": None, "rate": None}])
        loaded = self.store.load_assets(self.uid, "fd")
        self.assertEqual(len(loaded), 1)
        # Should load without crashing

    def test_unicode_in_fields(self):
        """Unicode characters (Hindi fund names, etc.) must survive."""
        self.store.save_assets(self.uid, "gold", [{"type": "physical", "note": "सोना 24K"}])
        loaded = self.store.load_assets(self.uid, "gold")
        self.assertEqual(loaded[0]["note"], "सोना 24K")

    def test_large_number_precision(self):
        """Large numbers (crores) must not lose precision."""
        self.store.save_assets(self.uid, "realestate",
                               [{"type": "plot", "current_value": 150000000}])  # 15 Cr
        loaded = self.store.load_assets(self.uid, "realestate")
        self.assertEqual(loaded[0]["current_value"], 150000000)

    def test_float_precision(self):
        """Interest rates and NAVs must preserve decimal precision."""
        self.store.save_assets(self.uid, "fd", [{"bank": "SBI", "amount": 100, "rate": 7.125}])
        loaded = self.store.load_assets(self.uid, "fd")
        self.assertAlmostEqual(loaded[0]["rate"], 7.125, places=3)

    def test_empty_string_fields(self):
        """Empty strings should not be confused with missing fields."""
        self.store.save_assets(self.uid, "esop", [{"company": "", "vested": 0}])
        loaded = self.store.load_assets(self.uid, "esop")
        self.assertIn("company", loaded[0])
        self.assertEqual(loaded[0]["company"], "")

    def test_extra_fields_preserved(self):
        """Unknown fields from LLM should be preserved, not dropped."""
        self.store.save_assets(self.uid, "fd",
                               [{"bank": "SBI", "amount": 100, "unexpected_field": "keep me"}])
        loaded = self.store.load_assets(self.uid, "fd")
        self.assertEqual(loaded[0]["unexpected_field"], "keep me")


if __name__ == "__main__":
    unittest.main()
