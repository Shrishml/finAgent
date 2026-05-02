"""Tests for unified asset layer: reconcile_and_save, load_mf_assets, migration."""
import pytest
from datetime import date

from finagent.models.mf import MFHolding, MFTransaction
from finagent.storage import (
    reconcile_and_save, load_mf_assets,
    clear_mf_assets, save_assets, load_assets, get_or_create_user,
    save_holdings, load_holdings,
)
from finagent.storage.database import get_db
from finagent.storage.models import UserAsset
from finagent.storage.asset_ops import _scheme_match


@pytest.fixture
async def uid():
    user_id = await get_or_create_user("test-unified-asset", "unified@test.com", "Test Unified")
    await clear_mf_assets(user_id)  # Clean up before each test
    return user_id


def _make_holding(name="Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
                  folio="TEST-001", value=94000, invested=90000, units=1140,
                  nav=83, amfi="122639", plan="direct") -> MFHolding:
    return MFHolding(
        scheme_name=name, folio=folio, amc="PPFAS", amfi_code=amfi,
        plan=plan, units=units, nav=nav, current_value=value,
        invested_value=invested,
        transactions=[MFTransaction(date=date(2024, 1, 15), description="SIP",
                                    amount=5000, units=60.2, type="SIP")],
    )


class TestSchemeMatch:
    def test_exact_match(self):
        assert _scheme_match("Parag Parikh Flexi Cap Fund", "Parag Parikh Flexi Cap Fund")

    def test_prefix_match(self):
        assert _scheme_match(
            "Parag Parikh Flexi Cap Fund - Direct Plan - Growth",
            "Parag Parikh Flexi Cap Fund"
        )

    def test_reverse_prefix(self):
        assert _scheme_match(
            "Parag Parikh Flexi Cap",
            "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
        )

    def test_fuzzy_match(self):
        assert _scheme_match(
            "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth",
            "HDFC Mid Cap Opportunities"
        )

    def test_no_match(self):
        assert not _scheme_match("Parag Parikh Flexi Cap", "HDFC Mid Cap Opportunities")

    def test_empty(self):
        assert not _scheme_match("", "Parag Parikh")
        assert not _scheme_match("Parag Parikh", "")


@pytest.mark.asyncio
class TestReconcileAndSave:
    async def test_save_verified_holdings(self, uid):
        user_id = uid
        await clear_mf_assets(user_id)
        h = _make_holding()
        result = await reconcile_and_save(user_id, "mf", [h])
        assert result["saved"] == 1
        assert result["new"] == 1
        assert result["replaced"] == 0

    async def test_replaces_declared_on_match(self, uid):
        user_id = uid
        await clear_mf_assets(user_id)
        # User declared via chat
        await save_assets(user_id, "mf", [
            {"scheme": "Parag Parikh Flexi Cap", "monthly_sip": 5000, "current_value": 100000}
        ], source="declared")
        # CAS upload with same fund
        h = _make_holding(value=94000)
        result = await reconcile_and_save(user_id, "mf", [h])
        assert result["replaced"] == 1
        # Declared entry replaced by verified — only 1 MF total
        holdings = await load_mf_assets(user_id)
        assert len(holdings) == 1
        assert holdings[0].current_value == 94000

    async def test_keeps_unmatched_declared(self, uid):
        user_id = uid
        await clear_mf_assets(user_id)
        # User declared a fund not in CAS
        await save_assets(user_id, "mf", [
            {"scheme": "SBI Small Cap Fund", "monthly_sip": 3000, "current_value": 50000}
        ], source="declared")
        # CAS has different fund
        h = _make_holding()
        await reconcile_and_save(user_id, "mf", [h])
        # SBI declared entry should remain alongside verified Parag Parikh
        all_mf = await load_assets(user_id, "mf")
        sbi = [a for a in all_mf if a.get("scheme") == "SBI Small Cap Fund"]
        assert len(sbi) == 1

    async def test_re_upload_replaces_verified(self, uid):
        user_id = uid
        await clear_mf_assets(user_id)
        h1 = _make_holding(value=90000)
        await reconcile_and_save(user_id, "mf", [h1])
        # Re-upload with updated value
        h2 = _make_holding(value=95000)
        await reconcile_and_save(user_id, "mf", [h2])
        holdings = await load_mf_assets(user_id)
        assert len(holdings) == 1
        assert holdings[0].current_value == 95000

    async def test_multiple_holdings(self, uid):
        user_id = uid
        await clear_mf_assets(user_id)
        holdings = [
            _make_holding(name="Fund A - Direct", folio="F1", value=50000),
            _make_holding(name="Fund B - Direct", folio="F2", value=30000),
        ]
        result = await reconcile_and_save(user_id, "mf", holdings)
        assert result["saved"] == 2
        loaded = await load_mf_assets(user_id)
        assert len(loaded) == 2


@pytest.mark.asyncio
class TestLoadMfAssets:
    async def test_loads_verified(self, uid):
        user_id = uid
        await clear_mf_assets(user_id)
        await reconcile_and_save(user_id, "mf", [_make_holding()])
        holdings = await load_mf_assets(user_id)
        assert len(holdings) == 1
        assert holdings[0].scheme_name == "Parag Parikh Flexi Cap Fund - Direct Plan - Growth"
        assert len(holdings[0].transactions) == 1

    async def test_loads_legacy_declared(self, uid):
        user_id = uid
        await clear_mf_assets(user_id)
        await save_assets(user_id, "mf", [
            {"scheme": "SBI Small Cap", "current_value": 50000, "monthly_sip": 3000}
        ], source="declared")
        holdings = await load_mf_assets(user_id)
        assert len(holdings) == 1
        assert holdings[0].scheme_name == "SBI Small Cap"
        assert holdings[0].current_value == 50000

    async def test_loads_both_verified_and_declared(self, uid):
        user_id = uid
        await clear_mf_assets(user_id)
        await reconcile_and_save(user_id, "mf", [_make_holding()])
        await save_assets(user_id, "mf", [
            {"scheme": "SBI Small Cap", "current_value": 50000}
        ], source="declared")
        holdings = await load_mf_assets(user_id)
        assert len(holdings) == 2

    async def test_skips_zero_value(self, uid):
        user_id = uid
        await clear_mf_assets(user_id)
        await reconcile_and_save(user_id, "mf", [_make_holding(value=0, units=0)])
        holdings = await load_mf_assets(user_id)
        assert len(holdings) == 0

    async def test_transaction_roundtrip(self, uid):
        user_id = uid
        await clear_mf_assets(user_id)
        h = _make_holding()
        await reconcile_and_save(user_id, "mf", [h])
        loaded = await load_mf_assets(user_id)
        t = loaded[0].transactions[0]
        assert t.date == date(2024, 1, 15)
        assert t.amount == 5000
        assert t.type == "SIP"


@pytest.mark.asyncio
class TestSourceColumns:
    async def test_verified_has_source_metadata(self, uid):
        user_id = uid
        await clear_mf_assets(user_id)
        await reconcile_and_save(user_id, "mf", [_make_holding()])
        async with get_db() as db:
            from sqlalchemy import select
            stmt = select(UserAsset).where(
                UserAsset.user_id == user_id,
                UserAsset.asset_type == "mf"
            )
            result = await db.execute(stmt)
            row = result.scalar_one()
        assert row.source == "verified"
        assert row.source_detail == "cas_upload"
        assert row.verified_at is not None

    async def test_declared_has_default_source(self, uid):
        user_id = uid
        await clear_mf_assets(user_id)
        await save_assets(user_id, "mf", [{"scheme": "Test", "current_value": 1000}], source="declared")
        async with get_db() as db:
            from sqlalchemy import select
            stmt = select(UserAsset).where(
                UserAsset.user_id == user_id,
                UserAsset.asset_type == "mf",
                UserAsset.source == "declared"
            )
            result = await db.execute(stmt)
            row = result.scalar_one_or_none()
        assert row is not None
        assert row.source == "declared"
