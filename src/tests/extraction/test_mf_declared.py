"""Tests for declared MF SIP extraction."""
import pytest
import uuid

from finagent.models.profile import UserProfile
from finagent.agents.onboarding import apply_extractions
from finagent.storage import load_assets, get_or_create_user, save_assets


@pytest.fixture
async def mf_uid():
    return await get_or_create_user(f"test-mf-{uuid.uuid4().hex[:8]}", "mf@test.com", "Test MF")


@pytest.mark.asyncio
class TestMfDeclaredExtraction:
    async def test_basic_sip_extraction(self, mf_uid):
        p = UserProfile(user_id=mf_uid)
        await apply_extractions(p, {"mf_sips": [
            {"scheme": "Edelweiss Mid Cap", "monthly_sip": 14000, "category": "mid_cap"},
            {"scheme": "Parag Parikh Flexi Cap", "monthly_sip": 5600, "category": "flexi_cap"},
        ]})
        items = await load_assets(mf_uid, "mf")
        assert len(items) == 2
        assert items[0]["scheme"] == "Edelweiss Mid Cap"
        assert items[1]["monthly_sip"] == 5600

    async def test_merge_with_existing(self, mf_uid):
        await save_assets(mf_uid, "mf", [{"scheme": "Nifty 50 Index", "monthly_sip": 5000}], source="declared")
        p = UserProfile(user_id=mf_uid)
        await apply_extractions(p, {"mf_sips": [
            {"scheme": "Nifty 50 Index", "monthly_sip": 8000},  # update existing
            {"scheme": "UTI Gold ETF", "monthly_sip": 3000},    # new
        ]})
        items = await load_assets(mf_uid, "mf")
        assert len(items) == 2
        nifty = next(i for i in items if "Nifty" in i["scheme"])
        assert nifty["monthly_sip"] == 8000  # updated

    async def test_skips_invalid_entries(self, mf_uid):
        p = UserProfile(user_id=mf_uid)
        await apply_extractions(p, {"mf_sips": [
            {"scheme": "Valid Fund", "monthly_sip": 5000},
            {"not_a_scheme": True},  # invalid
            "just a string",         # invalid
        ]})
        items = await load_assets(mf_uid, "mf")
        valid = [i for i in items if i.get("scheme") == "Valid Fund"]
        assert len(valid) == 1

    async def test_not_on_profile(self, mf_uid):
        p = UserProfile(user_id=mf_uid)
        await apply_extractions(p, {"mf_sips": [{"scheme": "Test", "monthly_sip": 1000}], "age": 25})
        assert p.age == 25
        assert not hasattr(p, "mf_sips")

    async def test_allocation_pct_extracted(self, mf_uid):
        p = UserProfile(user_id=mf_uid)
        await apply_extractions(p, {"mf_sips": [
            {"scheme": "Edelweiss Mid Cap", "allocation_pct": 25, "category": "mid_cap"},
            {"scheme": "Parag Parikh Flexi Cap", "monthly_sip": 5600, "allocation_pct": 10, "category": "flexi_cap"},
        ]})
        items = await load_assets(mf_uid, "mf")
        assert len(items) == 2
        edel = next(i for i in items if "Edelweiss" in i["scheme"])
        assert edel["allocation_pct"] == 25
        assert edel.get("monthly_sip") is None  # only pct given
        ppfc = next(i for i in items if "Parag" in i["scheme"])
        assert ppfc["allocation_pct"] == 10
        assert ppfc["monthly_sip"] == 5600  # both given
