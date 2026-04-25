"""Tests for EPF/PPF/NPS extraction into user_assets."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from finagent.models.profile import UserProfile
from finagent.agents.onboarding import apply_extractions
from finagent.storage.sqlite import save_assets, load_assets, get_or_create_user


def _uid():
    return get_or_create_user("test-extraction-assets", "ext@test.com", "Test Ext")


class TestEpfPpfExtraction:
    def test_ppf_epf_saved_to_assets(self):
        uid = _uid()
        p = UserProfile(user_id=uid)
        apply_extractions(p, {"ppf_balance": 300000, "epf_balance": 150000, "epf_monthly": 5000})
        items = load_assets(uid, "epf_ppf")
        assert len(items) == 1
        assert items[0]["ppf_balance"] == 300000
        assert items[0]["epf_balance"] == 150000
        assert items[0]["epf_monthly"] == 5000

    def test_merges_with_existing(self):
        uid = _uid()
        save_assets(uid, "epf_ppf", [{"epf_balance": 100000}])
        p = UserProfile(user_id=uid)
        apply_extractions(p, {"ppf_balance": 300000})
        items = load_assets(uid, "epf_ppf")
        assert items[0]["epf_balance"] == 100000  # preserved
        assert items[0]["ppf_balance"] == 300000  # added


class TestNpsExtraction:
    def test_nps_saved_to_assets(self):
        uid = _uid()
        p = UserProfile(user_id=uid)
        apply_extractions(p, {"nps_balance": 200000, "nps_monthly": 3000})
        items = load_assets(uid, "nps")
        assert len(items) == 1
        assert items[0]["nps_balance"] == 200000
        assert items[0]["nps_monthly"] == 3000

    def test_merges_with_existing(self):
        uid = _uid()
        save_assets(uid, "nps", [{"nps_balance": 50000}])
        p = UserProfile(user_id=uid)
        apply_extractions(p, {"nps_monthly": 3000})
        items = load_assets(uid, "nps")
        assert items[0]["nps_balance"] == 50000  # preserved
        assert items[0]["nps_monthly"] == 3000  # added


class TestAssetFieldsNotOnProfile:
    def test_ppf_nps_not_set_on_profile(self):
        p = UserProfile(user_id=_uid())
        apply_extractions(p, {"ppf_balance": 300000, "nps_monthly": 3000, "monthly_income": 75000})
        assert p.monthly_income == 75000
        assert not hasattr(p, "ppf_balance")
        assert not hasattr(p, "nps_monthly")


class TestMixedExtraction:
    def test_profile_and_assets_together(self):
        """A real-world message extracts both profile fields and asset fields."""
        uid = _uid()
        p = UserProfile(user_id=uid)
        changed = apply_extractions(p, {
            "age": 25, "monthly_income": 75000, "risk_tolerance": "Aggressive",
            "ppf_balance": 300000, "nps_monthly": 3000, "epf_monthly": 5000,
        })
        assert changed is True
        assert p.age == 25
        assert p.monthly_income == 75000
        assert load_assets(uid, "epf_ppf")[0]["ppf_balance"] == 300000
        assert load_assets(uid, "nps")[0]["nps_monthly"] == 3000
