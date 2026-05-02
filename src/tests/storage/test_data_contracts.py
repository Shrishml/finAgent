"""Data contract tests: verify every asset type survives the full round-trip.

Extract → save_assets → load_assets → verify all fields present with correct types.
These catch silent data loss, type corruption, and field renaming bugs.
"""
import pytest

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


@pytest.fixture
async def store_and_uid():
    import finagent.storage as store
    uid = await store.get_or_create_user("test-contract", "c@test.com", "Contract")
    # Clean up all asset types before each test
    for asset_type in ASSET_CONTRACTS.keys():
        await store.save_assets(uid, asset_type, [])
    return store, uid


@pytest.mark.asyncio
class TestAssetRoundTrip:
    """For every asset type: save → load → verify all fields survive."""

    @pytest.mark.parametrize("asset_type,contract", ASSET_CONTRACTS.items())
    async def test_round_trip_asset_type(self, store_and_uid, asset_type, contract):
        """Every asset type's sample data must survive save→load unchanged."""
        store, uid = store_and_uid
        sample = contract["sample"].copy()
        await store.save_assets(uid, asset_type, [sample])
        loaded = await store.load_assets(uid, asset_type)
        assert len(loaded) == 1, f"{asset_type}: expected 1 row, got {len(loaded)}"
        data = loaded[0]
        for key, val in sample.items():
            assert key in data, f"{asset_type}: field '{key}' lost in round-trip"
            assert data[key] == val, f"{asset_type}.{key}: saved {val!r}, loaded {data[key]!r}"

    @pytest.mark.parametrize("asset_type,contract", ASSET_CONTRACTS.items())
    async def test_required_fields_present(self, store_and_uid, asset_type, contract):
        """Required fields must exist and have correct types after load."""
        store, uid = store_and_uid
        await store.save_assets(uid, asset_type, [contract["sample"]])
        loaded = (await store.load_assets(uid, asset_type))[0]
        for field, expected_type in contract["required"].items():
            assert field in loaded, f"{asset_type}: required field '{field}' missing"
            assert isinstance(loaded[field], expected_type), \
                f"{asset_type}.{field}: expected {expected_type}, got {type(loaded[field])}"

    @pytest.mark.parametrize("asset_type,contract", ASSET_CONTRACTS.items())
    async def test_numeric_fields_are_numbers(self, store_and_uid, asset_type, contract):
        """Numeric fields must load as int or float, not strings."""
        store, uid = store_and_uid
        await store.save_assets(uid, asset_type, [contract["sample"]])
        loaded = (await store.load_assets(uid, asset_type))[0]
        for field in contract.get("numeric", []):
            if field in loaded and loaded[field] is not None:
                assert isinstance(loaded[field], (int, float)), \
                    f"{asset_type}.{field}: expected number, got {type(loaded[field])}"

    async def test_multiple_items_per_type(self, store_and_uid):
        """Multiple assets of same type must all survive."""
        store, uid = store_and_uid
        fd1 = {"bank": "SBI", "amount": 500000, "rate": 7.1}
        fd2 = {"bank": "HDFC", "amount": 300000, "rate": 6.8}
        await store.save_assets(uid, "fd", [fd1, fd2])
        loaded = await store.load_assets(uid, "fd")
        assert len(loaded) == 2
        banks = {d["bank"] for d in loaded}
        assert banks == {"SBI", "HDFC"}

    async def test_save_overwrites_not_appends(self, store_and_uid):
        """save_assets replaces all items of that type, not appends."""
        store, uid = store_and_uid
        await store.save_assets(uid, "fd", [{"bank": "SBI", "amount": 100}])
        await store.save_assets(uid, "fd", [{"bank": "HDFC", "amount": 200}])
        loaded = await store.load_assets(uid, "fd")
        assert len(loaded) == 1
        assert loaded[0]["bank"] == "HDFC"

    async def test_empty_list_clears_assets(self, store_and_uid):
        """Saving empty list should remove all assets of that type."""
        store, uid = store_and_uid
        await store.save_assets(uid, "gold", [{"type": "sgb", "value": 100}])
        await store.save_assets(uid, "gold", [])
        loaded = await store.load_assets(uid, "gold")
        assert len(loaded) == 0

    async def test_asset_types_isolated(self, store_and_uid):
        """Saving one asset type must not affect another."""
        store, uid = store_and_uid
        await store.save_assets(uid, "fd", [{"bank": "SBI", "amount": 100}])
        await store.save_assets(uid, "gold", [{"type": "sgb", "value": 200}])
        await store.save_assets(uid, "fd", [{"bank": "HDFC", "amount": 300}])
        gold = await store.load_assets(uid, "gold")
        assert len(gold) == 1
        assert gold[0]["value"] == 200


@pytest.fixture
async def extract_fixture():
    import finagent.storage as store
    uid = await store.get_or_create_user("test-extract", "e@test.com", "Extract")
    # Clean up all asset types before each test
    for asset_type in ASSET_CONTRACTS.keys():
        await store.save_assets(uid, asset_type, [])
    return store, uid


@pytest.mark.asyncio
class TestExtractionToStorage:
    """Test that apply_extractions correctly routes data to storage."""

    def _profile(self, uid):
        from finagent.models.profile import UserProfile
        return UserProfile(user_id=uid)

    async def test_epf_extraction_saves_to_assets(self, extract_fixture):
        store, uid = extract_fixture
        from finagent.agents.onboarding import apply_extractions
        p = self._profile(uid)
        await apply_extractions(p, {"epf_balance": 850000, "epf_contribution": 15000})
        loaded = await store.load_assets(uid, "epf_ppf")
        assert len(loaded) == 1
        assert loaded[0]["epf_balance"] == 850000
        assert loaded[0]["epf_contribution"] == 15000

    async def test_mf_sip_extraction_saves_to_assets(self, extract_fixture):
        store, uid = extract_fixture
        from finagent.agents.onboarding import apply_extractions
        p = self._profile(uid)
        await apply_extractions(p, {"mf_sips": [
            {"scheme": "PPFAS Flexi Cap", "monthly_sip": 10000, "current_value": 250000}
        ]})
        loaded = await store.load_assets(uid, "mf")
        assert len(loaded) == 1
        assert loaded[0]["scheme"] == "PPFAS Flexi Cap"
        assert loaded[0]["monthly_sip"] == 10000

    async def test_fd_extraction_saves_to_assets(self, extract_fixture):
        store, uid = extract_fixture
        from finagent.agents.onboarding import apply_extractions
        p = self._profile(uid)
        await apply_extractions(p, {"fds": [
            {"bank": "SBI", "amount": 500000, "rate": 7.1, "maturity": "2027-06"}
        ]})
        loaded = await store.load_assets(uid, "fd")
        assert len(loaded) == 1
        assert loaded[0]["bank"] == "SBI"
        assert loaded[0]["amount"] == 500000

    async def test_gold_extraction_saves_to_assets(self, extract_fixture):
        store, uid = extract_fixture
        from finagent.agents.onboarding import apply_extractions
        p = self._profile(uid)
        await apply_extractions(p, {"gold": [
            {"type": "sgb", "current_value": 300000, "weight_grams": 50}
        ]})
        loaded = await store.load_assets(uid, "gold")
        assert len(loaded) == 1
        # current_value gets normalized to value
        assert loaded[0].get("value", loaded[0].get("current_value")) == 300000

    async def test_realestate_extraction_saves_to_assets(self, extract_fixture):
        store, uid = extract_fixture
        from finagent.agents.onboarding import apply_extractions
        p = self._profile(uid)
        await apply_extractions(p, {"real_estate": [
            {"type": "self_occupied", "location": "Bangalore",
             "current_value": 8000000, "purchase_price": 5000000}
        ]})
        loaded = await store.load_assets(uid, "realestate")
        assert len(loaded) == 1
        assert loaded[0]["current_value"] == 8000000

    async def test_esop_extraction_saves_to_assets(self, extract_fixture):
        store, uid = extract_fixture
        from finagent.agents.onboarding import apply_extractions
        p = self._profile(uid)
        await apply_extractions(p, {"esop_company": "Amazon", "esop_vested": 5000000,
                              "esop_unvested": 3000000})
        loaded = await store.load_assets(uid, "esop")
        assert len(loaded) == 1
        assert loaded[0]["company"] == "Amazon"
        assert loaded[0]["vested"] == 5000000

    async def test_profile_fields_saved_to_profile(self, extract_fixture):
        """Profile fields (income, expenses) go to profile, not assets."""
        store, uid = extract_fixture
        from finagent.agents.onboarding import apply_extractions
        p = self._profile(uid)
        await apply_extractions(p, {"monthly_income": 150000, "age": 30, "name": "Suraj"})
        assert p.monthly_income == 150000
        assert p.age == 30
        assert p.name == "Suraj"

    async def test_loan_extraction_saves_to_profile(self, extract_fixture):
        """Loans are stored on the profile object, not in user_assets."""
        store, uid = extract_fixture
        from finagent.agents.onboarding import apply_extractions
        p = self._profile(uid)
        await apply_extractions(p, {"loans": [
            {"type": "home", "principal": 5000000, "emi": 45000, "rate": 8.5}
        ]})
        assert len(p.loans) == 1
        assert p.loans[0]["type"] == "home"
        assert p.loans[0]["principal"] == 5000000

    async def test_update_existing_asset_merges(self, extract_fixture):
        """Second extraction for same asset type should merge, not duplicate."""
        store, uid = extract_fixture
        from finagent.agents.onboarding import apply_extractions
        p = self._profile(uid)
        await apply_extractions(p, {"epf_balance": 500000})
        await apply_extractions(p, {"epf_contribution": 15000})
        loaded = await store.load_assets(uid, "epf_ppf")
        assert len(loaded) == 1
        assert loaded[0]["epf_balance"] == 500000
        assert loaded[0]["epf_contribution"] == 15000

    async def test_pending_items_not_saved(self, extract_fixture):
        """Incomplete mentions (pending) should NOT create asset rows."""
        store, uid = extract_fixture
        from finagent.agents.onboarding import apply_extractions
        p = self._profile(uid)
        await apply_extractions(p, {"mf_sips": [{"scheme": "ICICI Small Cap"}],
                              "_pending": ["ICICI Small Cap: no amount provided"]})
        loaded = await store.load_assets(uid, "mf")
        # Should not save MF with only scheme name and no data
        assert len(loaded) == 0


@pytest.fixture
async def corrupt_fixture():
    import finagent.storage as store
    uid = await store.get_or_create_user("test-corrupt", "x@test.com", "Corrupt")
    # Clean up all asset types before each test
    for asset_type in ASSET_CONTRACTS.keys():
        await store.save_assets(uid, asset_type, [])
    return store, uid


@pytest.mark.asyncio
class TestDataCorruptionGuards:
    """Test that bad data doesn't silently corrupt storage."""

    async def test_none_values_handled(self, corrupt_fixture):
        """None values in data should not cause load failures."""
        store, uid = corrupt_fixture
        await store.save_assets(uid, "fd", [{"bank": "SBI", "amount": None, "rate": None}])
        loaded = await store.load_assets(uid, "fd")
        assert len(loaded) == 1
        # Should load without crashing

    async def test_unicode_in_fields(self, corrupt_fixture):
        """Unicode characters (Hindi fund names, etc.) must survive."""
        store, uid = corrupt_fixture
        await store.save_assets(uid, "gold", [{"type": "physical", "note": "सोना 24K"}])
        loaded = await store.load_assets(uid, "gold")
        assert loaded[0]["note"] == "सोना 24K"

    async def test_large_number_precision(self, corrupt_fixture):
        """Large numbers (crores) must not lose precision."""
        store, uid = corrupt_fixture
        await store.save_assets(uid, "realestate",
                               [{"type": "plot", "current_value": 150000000}])  # 15 Cr
        loaded = await store.load_assets(uid, "realestate")
        assert loaded[0]["current_value"] == 150000000

    async def test_float_precision(self, corrupt_fixture):
        """Interest rates and NAVs must preserve decimal precision."""
        store, uid = corrupt_fixture
        await store.save_assets(uid, "fd", [{"bank": "SBI", "amount": 100, "rate": 7.125}])
        loaded = await store.load_assets(uid, "fd")
        assert abs(loaded[0]["rate"] - 7.125) < 0.001

    async def test_empty_string_fields(self, corrupt_fixture):
        """Empty strings should not be confused with missing fields."""
        store, uid = corrupt_fixture
        await store.save_assets(uid, "esop", [{"company": "", "vested": 0}])
        loaded = await store.load_assets(uid, "esop")
        assert "company" in loaded[0]
        assert loaded[0]["company"] == ""

    async def test_extra_fields_preserved(self, corrupt_fixture):
        """Unknown fields from LLM should be preserved, not dropped."""
        store, uid = corrupt_fixture
        await store.save_assets(uid, "fd",
                               [{"bank": "SBI", "amount": 100, "unexpected_field": "keep me"}])
        loaded = await store.load_assets(uid, "fd")
        assert loaded[0]["unexpected_field"] == "keep me"
