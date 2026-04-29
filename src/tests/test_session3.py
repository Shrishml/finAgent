"""Tests for Session 3: orchestrator, API."""
import pytest
from unittest.mock import patch, AsyncMock

from finagent.orchestrator.engine import handle_query
from finagent.storage import sqlite as storage_mod


# --- Orchestrator ---

class TestOrchestrator:
    @pytest.fixture(autouse=True)
    def use_tmp_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage_mod, "_DB_DIR", tmp_path)
        monkeypatch.setattr(storage_mod, "_DB_PATH", tmp_path / "test.db")

    @pytest.mark.asyncio
    async def test_general_domain_returns_help(self):
        with patch("finagent.orchestrator.engine.classify_intent", new_callable=AsyncMock,
                   return_value={"domain": "general", "mode": "analyze"}):
            result = await handle_query("hello")
            assert "mutual funds" in result.lower()

    @pytest.mark.asyncio
    async def test_mf_no_data(self):
        with patch("finagent.orchestrator.engine.classify_intent", new_callable=AsyncMock,
                   return_value={"domain": "mf", "mode": "analyze"}):
            result = await handle_query("What are my expense ratios?")
            assert "upload" in result.lower()


# --- API (import check) ---

class TestAPIImport:
    def test_app_imports(self):
        from finagent.main import app
        assert app.title == "FinAgent"

    def test_routes_exist(self):
        from finagent.main import app
        routes = [r.path for r in app.routes]
        assert "/" in routes
        assert "/upload" in routes
        assert "/chat" in routes
        assert "/holdings" in routes
