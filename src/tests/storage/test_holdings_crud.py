"""Tests for MF holdings storage CRUD and NAV cache."""
import pytest

from finagent.models.mf import MFHolding
import finagent.storage as storage_mod


@pytest.fixture
async def holdings_uid():
    uid = await storage_mod.get_or_create_user("holdings-test", "h@test.com", "Holdings")
    await storage_mod.clear_holdings(user_id=uid)
    return uid


@pytest.mark.asyncio
class TestHoldingsCRUD:
    """Holdings save/load/clear operations."""

    def _make_holding(self, name="Test Fund", folio="F1"):
        return MFHolding(scheme_name=name, folio=folio, amc="Test AMC",
                         current_value=50000, expense_ratio=0.01)

    async def test_save_and_load(self, holdings_uid):
        h = self._make_holding()
        await storage_mod.save_holdings([h], user_id=holdings_uid)
        loaded = await storage_mod.load_holdings(user_id=holdings_uid)
        assert len(loaded) == 1
        assert loaded[0].scheme_name == "Test Fund"
        assert loaded[0].current_value == 50000

    async def test_upsert_replaces_by_folio(self, holdings_uid):
        """Second save with same folio+scheme replaces the first."""
        h1 = self._make_holding(name="Fund A", folio="F1")
        await storage_mod.save_holdings([h1], user_id=holdings_uid)
        h2 = MFHolding(scheme_name="Fund A", folio="F1", amc="Test", current_value=60000)
        await storage_mod.save_holdings([h2], user_id=holdings_uid)
        loaded = await storage_mod.load_holdings(user_id=holdings_uid)
        assert len(loaded) == 1
        assert loaded[0].current_value == 60000

    async def test_multiple_holdings(self, holdings_uid):
        await storage_mod.save_holdings([
            self._make_holding("Fund A", "F1"),
            self._make_holding("Fund B", "F2"),
        ], user_id=holdings_uid)
        assert len(await storage_mod.load_holdings(user_id=holdings_uid)) == 2

    async def test_clear(self, holdings_uid):
        await storage_mod.save_holdings([self._make_holding()], user_id=holdings_uid)
        await storage_mod.clear_holdings(user_id=holdings_uid)
        assert len(await storage_mod.load_holdings(user_id=holdings_uid)) == 0


@pytest.mark.asyncio
class TestNAVCache:
    """NAV cache read/write."""

    async def test_save_and_retrieve(self):
        await storage_mod.save_nav_cache("120503", 45.67, "Axis Bluechip", 0.005)
        cached = await storage_mod.get_cached_nav("120503")
        assert cached["nav"] == 45.67
        assert cached["expense_ratio"] == 0.005

    async def test_cache_miss_returns_none(self):
        assert await storage_mod.get_cached_nav("nonexistent") is None
