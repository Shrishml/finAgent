"""E2E onboarding test: UI cards → chat → verify LLM sees full profile context."""
import json
import pytest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient
from finagent.main import app
from finagent.storage import sqlite as storage_mod

_TEST_UID = 999


@pytest.fixture(autouse=True)
def use_tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_mod, "_DB_DIR", tmp_path)
    monkeypatch.setattr(storage_mod, "_DB_PATH", tmp_path / "test.db")


@pytest.fixture(autouse=True)
def mock_auth(monkeypatch):
    """Bypass auth — all requests return a fixed test user_id."""
    monkeypatch.setattr("finagent.main._get_user_id", lambda r: _TEST_UID)


@pytest.fixture
def client():
    return TestClient(app)


def _llm_resp(response: str, pillar_complete=False, extractions=None):
    return json.dumps({
        "extractions": extractions or {},
        "pillar_complete": pillar_complete,
        "pillar_skipped": False,
        "response": response,
        "dashboard_updates": [],
    })


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

    def _chat(self, client, msg, captured_prompts, llm_response):
        async def mock_complete(prompt, **kwargs):
            captured_prompts.append(prompt)
            return llm_response

        with patch("finagent.agents.onboarding.get_provider") as mock_prov:
            mock_llm = AsyncMock()
            mock_llm.complete = mock_complete
            mock_prov.return_value = mock_llm
            return client.post("/chat", data={"query": msg})

    def test_llm_receives_full_profile_during_goals_chat(self, client):
        """After UI cards, when chat asks about goals, the LLM prompt must contain card data."""
        self._submit_cards(client)
        client.post("/chat", data={"query": "__onboarding_init__"})

        captured = []
        resp = self._chat(client, "I want to buy a house in 5 years", captured,
                          _llm_resp("Great goal!", extractions={"goals_mentioned": ["house in 5 years"]}, pillar_complete=True))

        assert resp.status_code == 200
        assert len(captured) == 1
        prompt = captured[0]
        assert "150000" in prompt, "monthly_income missing"
        assert "80000" in prompt, "monthly_expenses missing"
        assert "28" in prompt, "age missing"
        assert "Bangalore" in prompt, "location missing"
        assert "married" in prompt, "marital_status missing"
        assert "500000" in prompt, "total_investments missing"
        assert "25000" in prompt, "emis missing"

    def test_llm_does_not_see_internal_state_fields(self, client):
        self._submit_cards(client)
        client.post("/chat", data={"query": "__onboarding_init__"})

        captured = []
        self._chat(client, "I want to save for retirement", captured,
                   _llm_resp("Tell me more about your goals."))

        profile_start = captured[0].index("CURRENT PROFILE:") + len("CURRENT PROFILE:")
        profile_end = captured[0].index("PILLARS COMPLETED:")
        profile_data = json.loads(captured[0][profile_start:profile_end].strip())
        assert "user_id" not in profile_data
        assert "pillars_completed" not in profile_data
        assert "onboarding_complete" not in profile_data

    def test_personalise_instruction_in_prompt(self, client):
        self._submit_cards(client)
        client.post("/chat", data={"query": "__onboarding_init__"})

        captured = []
        self._chat(client, "Let's talk about goals", captured,
                   _llm_resp("What goals do you have?"))

        assert "PERSONALISE" in captured[0]

    def test_wrapup_sees_full_context(self, client):
        client.put("/profile", json={
            "age": 30, "monthly_income": 200000, "monthly_expenses": 100000,
            "location": "Mumbai", "marital_status": "single",
            "term_cover": 5000000, "health_cover": 300000,
            "total_investments": 1000000,
            "goals_mentioned": ["retirement by 50", "Europe trip"],
            "pillars_completed": ["income", "expenses", "assets", "liabilities", "insurance", "goals"],
        })

        client.post("/chat", data={"query": "__onboarding_init__"})

        captured = []
        self._chat(client, "I'm okay with some risk", captured,
                   _llm_resp("Got it!", extractions={"risk_tolerance": "moderate"}, pillar_complete=True))

        prompt = captured[0]
        assert "200000" in prompt, "income missing during wrapup"
        assert "retirement" in prompt.lower() or "Europe" in prompt, "goals_mentioned missing"
        assert "wrapup" in prompt, "current_pillar should be wrapup"
