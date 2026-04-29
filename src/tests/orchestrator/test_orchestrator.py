"""Tests for orchestrator query handling and intent routing."""
import pytest
from unittest.mock import patch, AsyncMock

from finagent.orchestrator.engine import handle_query
from finagent.storage import sqlite as storage_mod


class TestHandleQuery:
    """Verify handle_query returns non-empty responses for different intents."""

    @pytest.fixture(autouse=True)
    def use_tmp_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage_mod, "_DB_DIR", tmp_path)
        monkeypatch.setattr(storage_mod, "_DB_PATH", tmp_path / "test.db")

    @pytest.mark.asyncio
    async def test_general_intent_returns_nonempty(self):
        """General domain queries should return a substantive response."""
        with patch("finagent.orchestrator.engine.classify_intent", new_callable=AsyncMock,
                   return_value={"domain": "general", "mode": "analyze"}):
            result = await handle_query("hello")
            assert isinstance(result, str)
            assert len(result) > 20, f"Response too short: {result!r}"

    @pytest.mark.asyncio
    async def test_mf_intent_without_data_returns_guidance(self):
        """MF query with no portfolio data should guide user (not crash)."""
        with patch("finagent.orchestrator.engine.classify_intent", new_callable=AsyncMock,
                   return_value={"domain": "mf", "mode": "analyze"}):
            result = await handle_query("What are my expense ratios?")
            assert isinstance(result, str)
            assert len(result) > 20, f"Response too short: {result!r}"


class TestAPIImport:
    """Verify FastAPI app loads and expected routes are registered."""

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
