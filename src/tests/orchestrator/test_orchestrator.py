"""Tests for orchestrator query handling and intent routing."""
import pytest
from unittest.mock import patch, AsyncMock, MagicMock

from finagent.orchestrator.engine import handle_query
import finagent.storage as storage_mod


def _mock_llm():
    """Create a mock LLM provider."""
    mock = MagicMock()
    mock.complete = AsyncMock(return_value="This is a helpful response about your financial question.")
    return mock


@pytest.mark.asyncio
class TestHandleQuery:
    """Verify handle_query returns non-empty responses for different intents."""

    async def test_general_intent_returns_nonempty(self):
        """General domain queries should return a substantive response."""
        with patch("finagent.orchestrator.engine.classify_intent", new_callable=AsyncMock,
                   return_value={"domain": "general", "mode": "analyze"}), \
             patch("finagent.llm.get_provider", return_value=_mock_llm()):
            result = await handle_query("hello")
            assert isinstance(result, str)
            assert len(result) > 20, f"Response too short: {result!r}"

    async def test_mf_intent_without_data_returns_guidance(self):
        """MF query with no portfolio data should guide user (not crash)."""
        with patch("finagent.orchestrator.engine.classify_intent", new_callable=AsyncMock,
                   return_value={"domain": "mf", "mode": "analyze"}), \
             patch("finagent.llm.get_provider", return_value=_mock_llm()):
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
