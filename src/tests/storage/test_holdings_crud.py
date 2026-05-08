"""Tests for MF holdings storage CRUD and NAV cache."""
import pytest

from finagent.models.mf import MFHolding
from finagent.storage import sqlite as storage_mod


class TestHoldingsCRUD:
    """Holdings save/load/clear operations."""

    @pytest.fixture(autouse=True)
    def use_tmp_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage_mod, "_DB_DIR", tmp_path)
        monkeypatch.setattr(storage_mod, "_DB_PATH", tmp_path / "test.db")

    def _make_holding(self, name="Test Fund", folio="F1"):
        return MFHolding(scheme_name=name, folio=folio, amc="Test AMC",
                         current_value=50000, expense_ratio=0.01)

    def test_save_and_load(self):
        h = self._make_holding()
        storage_mod.save_holdings([h], user_id=1)
        loaded = storage_mod.load_holdings(user_id=1)
        assert len(loaded) == 1
        assert loaded[0].scheme_name == "Test Fund"
        assert loaded[0].current_value == 50000

    def test_upsert_replaces_by_folio(self):
        """Second save with same folio+scheme replaces the first."""
        h1 = self._make_holding(name="Fund A", folio="F1")
        storage_mod.save_holdings([h1], user_id=1)
        h2 = MFHolding(scheme_name="Fund A", folio="F1", amc="Test", current_value=60000)
        storage_mod.save_holdings([h2], user_id=1)
        loaded = storage_mod.load_holdings(user_id=1)
        assert len(loaded) == 1
        assert loaded[0].current_value == 60000

    def test_multiple_holdings(self):
        storage_mod.save_holdings([
            self._make_holding("Fund A", "F1"),
            self._make_holding("Fund B", "F2"),
        ], user_id=1)
        assert len(storage_mod.load_holdings(user_id=1)) == 2

    def test_clear(self):
        storage_mod.save_holdings([self._make_holding()], user_id=1)
        storage_mod.clear_holdings(user_id=1)
        assert len(storage_mod.load_holdings(user_id=1)) == 0


class TestNAVCache:
    """NAV cache read/write."""

    @pytest.fixture(autouse=True)
    def use_tmp_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage_mod, "_DB_DIR", tmp_path)
        monkeypatch.setattr(storage_mod, "_DB_PATH", tmp_path / "test.db")

    def test_save_and_retrieve(self):
        storage_mod.save_nav_cache("120503", 45.67, "Axis Bluechip", 0.005)
        cached = storage_mod.get_cached_nav("120503")
        assert cached["nav"] == 45.67
        assert cached["expense_ratio"] == 0.005

    def test_cache_miss_returns_none(self):
        assert storage_mod.get_cached_nav("nonexistent") is None
