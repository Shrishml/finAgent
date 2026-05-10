"""E2E onboarding test: UI cards → chat → verify advisor LLM sees full profile context."""
import json
import os
import shutil
import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from finagent.main import app
import finagent.storage as storage_mod
from tests.conftest import async_return

_TEST_UID = 999


def _llm_available():
    """Check if an LLM provider is available."""
    if os.environ.get("GEMINI_API_KEY"):
        return True
    if shutil.which("gemini") or shutil.which("kiro-cli"):
        return True
    return False


@pytest.fixture(autouse=True)
def use_tmp_db(tmp_path, monkeypatch):
    from finagent.storage import database as db_mod
    import asyncio
    monkeypatch.setattr(storage_mod, "_DB_DIR", tmp_path)
    monkeypatch.setattr(storage_mod, "_DB_PATH", tmp_path / "test.db")
    test_db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", test_db_url)
    db_mod._engine = None
    db_mod._async_session_factory = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.run_until_complete(db_mod.init_db())


@pytest.fixture(autouse=True)
def mock_auth(monkeypatch):
    """Bypass auth — all requests return a fixed test user_id."""
    monkeypatch.setattr("finagent.api.deps._DEV_MODE", True)
    monkeypatch.setattr("finagent.api.deps.get_user_id", async_return(_TEST_UID))
    monkeypatch.setattr("finagent.api.chat.get_user_id", async_return(_TEST_UID))
    monkeypatch.setattr("finagent.api.profile.get_user_id", async_return(_TEST_UID))
    monkeypatch.setattr("finagent.api.deps.require_auth", async_return(_TEST_UID))


@pytest.fixture
def client():
    return TestClient(app)


@pytest.mark.skipif(not _llm_available(), reason="No LLM provider available")
class TestOnboardingE2EPersonalisation:

    def _submit_cards(self, client):
        client.put("/profile", json={
            "age": 28, "location": "Bangalore", "marital_status": "married", "kids": 1,
            "dependents": 2,
            "monthly_income": 150000, "monthly_expenses": 80000,
            "term_cover": 10000000, "health_cover": 500000,
            "total_investments": 500000, "emis": 25000,
            "pillars_completed": ["income", "expenses", "assets", "liabilities", "insurance"],
        })

    def _chat_capture_advisor(self, client, msg):
        """Send a chat message and capture the advisor LLM prompt.

        Mocks finagent.llm.get_provider so every LLM call is intercepted.
        Returns (response, list_of_prompts_sent_to_llm).
        """
        captured = []
        call_count = {"n": 0}

        async def mock_complete(prompt, **kwargs):
            captured.append(prompt)
            call_count["n"] += 1
            # 1st call = extraction → return no-data JSON
            # 2nd call = intent classification → return general/analyze
            # 3rd+ call = advisor → return a simple response
            if kwargs.get("json_mode") and call_count["n"] <= 2:
                if "Extract" in prompt:
                    return '{"extractions": {}, "has_data": false, "pending": []}'
                return '{"domain": "goals", "mode": "analyze"}'
            return "Great goal! Let me help you plan for that house."

        with patch("finagent.llm.get_provider") as mock_prov:
            mock_llm = AsyncMock()
            mock_llm.complete = mock_complete
            mock_prov.return_value = mock_llm
            resp = client.post("/chat", data={"query": msg})

        return resp, captured

    def test_llm_receives_full_profile_during_goals_chat(self, client):
        """After UI cards, when chat asks about goals, the advisor prompt must contain card data."""
        self._submit_cards(client)

        resp, captured = self._chat_capture_advisor(client, "I want to buy a house in 5 years")

        assert resp.status_code == 200
        # The advisor prompt is the last one (after extraction + classification)
        advisor_prompt = captured[-1]
        assert "150000" in advisor_prompt, "monthly_income missing from advisor prompt"
        assert "80000" in advisor_prompt, "monthly_expenses missing from advisor prompt"
        assert "28" in advisor_prompt, "age missing from advisor prompt"
        assert "Bangalore" in advisor_prompt, "location missing from advisor prompt"
        assert "married" in advisor_prompt, "marital_status missing from advisor prompt"
        assert "25000" in advisor_prompt, "emis missing from advisor prompt"

    def test_llm_does_not_see_internal_state_fields(self, client):
        """Internal fields like user_id, pillars_completed should not leak into advisor prompt."""
        self._submit_cards(client)

        _, captured = self._chat_capture_advisor(client, "I want to save for retirement")

        advisor_prompt = captured[-1]
        assert "user_id" not in advisor_prompt
        assert "pillars_completed" not in advisor_prompt
        assert "onboarding_complete" not in advisor_prompt

    def test_advisor_prompt_contains_tools(self, client):
        """Advisor prompt should include available action tools."""
        self._submit_cards(client)

        _, captured = self._chat_capture_advisor(client, "Let's talk about goals")

        advisor_prompt = captured[-1]
        assert "create_goal" in advisor_prompt, "create_goal tool missing from advisor prompt"
        assert "analyze_portfolio" in advisor_prompt, "analyze_portfolio tool missing"

    def test_wrapup_sees_full_context(self, client):
        """Profile with goals should be visible to the advisor."""
        client.put("/profile", json={
            "age": 30, "monthly_income": 200000, "monthly_expenses": 100000,
            "location": "Mumbai", "marital_status": "single",
            "term_cover": 5000000, "health_cover": 300000,
            "total_investments": 1000000,
            "goals_mentioned": ["retirement by 50", "Europe trip"],
            "pillars_completed": ["income", "expenses", "assets", "liabilities", "insurance", "goals"],
        })

        _, captured = self._chat_capture_advisor(client, "I'm okay with some risk")

        advisor_prompt = captured[-1]
        assert "200000" in advisor_prompt, "income missing from advisor prompt"
        assert "100000" in advisor_prompt, "expenses missing from advisor prompt"
        assert "Mumbai" in advisor_prompt, "location missing from advisor prompt"
