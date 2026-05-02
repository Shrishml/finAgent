"""Tests for EPF/PPF/NPS extraction into user_assets."""
import pytest

from finagent.models.profile import UserProfile
from finagent.agents.onboarding import apply_extractions
from finagent.storage import save_assets, load_assets, get_or_create_user


@pytest.fixture
async def uid():
    return await get_or_create_user("test-extraction-assets", "ext@test.com", "Test Ext")


@pytest.mark.asyncio
class TestEpfPpfExtraction:
    async def test_ppf_epf_saved_to_assets(self, uid):
        p = UserProfile(user_id=uid)
        await apply_extractions(p, {"ppf_balance": 300000, "epf_balance": 150000, "epf_contribution": 5000})
        items = await load_assets(uid, "epf_ppf")
        assert len(items) == 1
        assert items[0]["ppf_balance"] == 300000
        assert items[0]["epf_balance"] == 150000
        assert items[0]["epf_contribution"] == 5000

    async def test_merges_with_existing(self, uid):
        await save_assets(uid, "epf_ppf", [{"epf_balance": 100000}])
        p = UserProfile(user_id=uid)
        await apply_extractions(p, {"ppf_balance": 300000})
        items = await load_assets(uid, "epf_ppf")
        assert items[0]["epf_balance"] == 100000  # preserved
        assert items[0]["ppf_balance"] == 300000  # added


@pytest.mark.asyncio
class TestNpsExtraction:
    async def test_nps_saved_to_assets(self, uid):
        p = UserProfile(user_id=uid)
        await apply_extractions(p, {"nps_balance": 200000, "nps_contribution": 3000})
        items = await load_assets(uid, "nps")
        assert len(items) == 1
        assert items[0]["nps_balance"] == 200000
        assert items[0]["nps_contribution"] == 3000

    async def test_merges_with_existing(self, uid):
        await save_assets(uid, "nps", [{"nps_balance": 50000}])
        p = UserProfile(user_id=uid)
        await apply_extractions(p, {"nps_contribution": 3000})
        items = await load_assets(uid, "nps")
        assert items[0]["nps_balance"] == 50000  # preserved
        assert items[0]["nps_contribution"] == 3000  # added


@pytest.mark.asyncio
class TestAssetFieldsNotOnProfile:
    async def test_ppf_nps_not_set_on_profile(self, uid):
        p = UserProfile(user_id=uid)
        await apply_extractions(p, {"ppf_balance": 300000, "nps_contribution": 3000, "monthly_income": 75000})
        assert p.monthly_income == 75000
        assert not hasattr(p, "ppf_balance")
        assert not hasattr(p, "nps_contribution")


@pytest.mark.asyncio
class TestMixedExtraction:
    async def test_profile_and_assets_together(self, uid):
        """A real-world message extracts both profile fields and asset fields."""
        p = UserProfile(user_id=uid)
        changed = await apply_extractions(p, {
            "age": 25, "monthly_income": 75000, "risk_tolerance": "Aggressive",
            "ppf_balance": 300000, "nps_contribution": 3000, "epf_contribution": 5000,
        })
        assert changed is True
        assert p.age == 25
        assert p.monthly_income == 75000
        epf_items = await load_assets(uid, "epf_ppf")
        assert epf_items[0]["ppf_balance"] == 300000
        nps_items = await load_assets(uid, "nps")
        assert nps_items[0]["nps_contribution"] == 3000


@pytest.fixture
async def fd_uid():
    import uuid
    return await get_or_create_user(f"test-fd-{uuid.uuid4().hex[:8]}", "fd@t.com", "T")


@pytest.mark.asyncio
class TestFdExtraction:
    async def test_fd_extracted(self, fd_uid):
        p = UserProfile(user_id=fd_uid)
        await apply_extractions(p, {"fds": [
            {"bank": "Franklin Corporate Debt", "amount": 150000},
            {"bank": "Flexi FD", "amount": 150000},
        ]})
        items = await load_assets(fd_uid, "fd")
        assert len(items) == 2
        assert items[0]["amount"] == 150000

    async def test_fd_merge_existing(self):
        import uuid
        fd_uid = await get_or_create_user(f"test-fd-m-{uuid.uuid4().hex[:8]}", "fd@t.com", "T")
        await save_assets(fd_uid, "fd", [{"bank": "SBI", "amount": 500000}])
        p = UserProfile(user_id=fd_uid)
        await apply_extractions(p, {"fds": [
            {"bank": "SBI", "amount": 600000},  # update
            {"bank": "HDFC", "amount": 200000},  # new
        ]})
        items = await load_assets(fd_uid, "fd")
        assert len(items) == 2
        sbi = next(i for i in items if i["bank"] == "SBI")
        assert sbi["amount"] == 600000


@pytest.mark.asyncio
class TestGoldExtraction:
    async def test_gold_saved(self):
        import uuid
        gold_uid = await get_or_create_user(f"test-gold-{uuid.uuid4().hex[:8]}", "g@t.com", "T")
        p = UserProfile(user_id=gold_uid)
        changed = await apply_extractions(p, {"gold": [
            {"type": "physical", "value": 700000, "amount_invested": 500000},
        ]})
        assert changed is True
        items = await load_assets(gold_uid, "gold")
        assert len(items) == 1
        assert items[0]["type"] == "physical"
        assert items[0]["value"] == 700000
        assert items[0]["amount_invested"] == 500000

    async def test_gold_current_value_normalized(self):
        """LLM may return current_value instead of value — should be normalized."""
        import uuid
        gold_uid = await get_or_create_user(f"test-gold-cv-{uuid.uuid4().hex[:8]}", "g@t.com", "T")
        p = UserProfile(user_id=gold_uid)
        await apply_extractions(p, {"gold": [
            {"type": "sgb", "current_value": 300000},
        ]})
        items = await load_assets(gold_uid, "gold")
        assert items[0]["value"] == 300000
        assert "current_value" not in items[0]

    async def test_gold_merge_by_type(self):
        import uuid
        gold_uid = await get_or_create_user(f"test-gold-m-{uuid.uuid4().hex[:8]}", "g@t.com", "T")
        await save_assets(gold_uid, "gold", [{"type": "physical", "value": 500000}])
        p = UserProfile(user_id=gold_uid)
        await apply_extractions(p, {"gold": [
            {"type": "physical", "value": 700000},  # update
            {"type": "sgb", "value": 200000},  # new
        ]})
        items = await load_assets(gold_uid, "gold")
        assert len(items) == 2
        phys = next(i for i in items if i["type"] == "physical")
        assert phys["value"] == 700000
        sgb = next(i for i in items if i["type"] == "sgb")
        assert sgb["value"] == 200000

    async def test_gold_multiple_types(self):
        import uuid
        gold_uid = await get_or_create_user(f"test-gold-mt-{uuid.uuid4().hex[:8]}", "g@t.com", "T")
        p = UserProfile(user_id=gold_uid)
        await apply_extractions(p, {"gold": [
            {"type": "physical", "value": 700000, "weight_grams": 100},
            {"type": "sgb", "value": 300000},
            {"type": "digital", "value": 50000},
        ]})
        items = await load_assets(gold_uid, "gold")
        assert len(items) == 3


@pytest.mark.asyncio
class TestRealEstateExtraction:
    async def test_realestate_saved(self):
        import uuid
        re_uid = await get_or_create_user(f"test-re-{uuid.uuid4().hex[:8]}", "r@t.com", "T")
        p = UserProfile(user_id=re_uid)
        changed = await apply_extractions(p, {"real_estate": [
            {"type": "self_occupied", "location": "Bangalore", "current_value": 8000000, "purchase_price": 5000000},
        ]})
        assert changed is True
        items = await load_assets(re_uid, "realestate")
        assert len(items) == 1
        assert items[0]["location"] == "Bangalore"
        assert items[0]["current_value"] == 8000000

    async def test_realestate_merge_by_location(self):
        import uuid
        re_uid = await get_or_create_user(f"test-re-m-{uuid.uuid4().hex[:8]}", "r@t.com", "T")
        await save_assets(re_uid, "realestate", [{"type": "self_occupied", "location": "Bangalore", "current_value": 6000000}])
        p = UserProfile(user_id=re_uid)
        await apply_extractions(p, {"real_estate": [
            {"type": "self_occupied", "location": "Bangalore", "current_value": 8000000},  # update
            {"type": "rented", "location": "Pune", "current_value": 4000000, "rental_income": 15000},  # new
        ]})
        items = await load_assets(re_uid, "realestate")
        assert len(items) == 2
        blr = next(i for i in items if i["location"] == "Bangalore")
        assert blr["current_value"] == 8000000
        pune = next(i for i in items if i["location"] == "Pune")
        assert pune["rental_income"] == 15000

    async def test_realestate_no_location_appends(self):
        """Properties without location should always append, not merge."""
        import uuid
        re_uid = await get_or_create_user(f"test-re-nl-{uuid.uuid4().hex[:8]}", "r@t.com", "T")
        p = UserProfile(user_id=re_uid)
        await apply_extractions(p, {"real_estate": [
            {"type": "plot", "current_value": 2000000},
            {"type": "plot", "current_value": 3000000},
        ]})
        items = await load_assets(re_uid, "realestate")
        assert len(items) == 2
