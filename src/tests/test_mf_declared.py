"""Tests for declared MF SIP extraction."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from finagent.models.profile import UserProfile
from finagent.agents.onboarding import apply_extractions
from finagent.storage.sqlite import load_assets, get_or_create_user


def _uid():
    import uuid
    return get_or_create_user(f"test-mf-{uuid.uuid4().hex[:8]}", "mf@test.com", "Test MF")


class TestMfDeclaredExtraction:
    def test_basic_sip_extraction(self):
        uid = _uid()
        p = UserProfile(user_id=uid)
        apply_extractions(p, {"mf_sips": [
            {"scheme": "Edelweiss Mid Cap", "monthly_sip": 14000, "category": "mid_cap"},
            {"scheme": "Parag Parikh Flexi Cap", "monthly_sip": 5600, "category": "flexi_cap"},
        ]})
        items = load_assets(uid, "mf_declared")
        assert len(items) == 2
        assert items[0]["scheme"] == "Edelweiss Mid Cap"
        assert items[1]["monthly_sip"] == 5600

    def test_merge_with_existing(self):
        uid = _uid()
        from finagent.storage.sqlite import save_assets
        save_assets(uid, "mf_declared", [{"scheme": "Nifty 50 Index", "monthly_sip": 5000}])
        p = UserProfile(user_id=uid)
        apply_extractions(p, {"mf_sips": [
            {"scheme": "Nifty 50 Index", "monthly_sip": 8000},  # update existing
            {"scheme": "UTI Gold ETF", "monthly_sip": 3000},    # new
        ]})
        items = load_assets(uid, "mf_declared")
        assert len(items) == 2
        nifty = next(i for i in items if "Nifty" in i["scheme"])
        assert nifty["monthly_sip"] == 8000  # updated

    def test_skips_invalid_entries(self):
        uid = _uid()
        p = UserProfile(user_id=uid)
        apply_extractions(p, {"mf_sips": [
            {"scheme": "Valid Fund", "monthly_sip": 5000},
            {"not_a_scheme": True},  # invalid
            "just a string",         # invalid
        ]})
        items = load_assets(uid, "mf_declared")
        valid = [i for i in items if i.get("scheme") == "Valid Fund"]
        assert len(valid) == 1

    def test_not_on_profile(self):
        p = UserProfile(user_id=_uid())
        apply_extractions(p, {"mf_sips": [{"scheme": "Test", "monthly_sip": 1000}], "age": 25})
        assert p.age == 25
        assert not hasattr(p, "mf_sips")
