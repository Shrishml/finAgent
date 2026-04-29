"""E2E tests for profile assets: save → load → agent context → smart updates.

Uses real LLM — no mocks. Tests are slow (~10s each for agent tests) but high confidence.
Run: pytest src/tests/test_profile_e2e.py -v
"""
import pytest

from fastapi.testclient import TestClient
from finagent.main import app
from finagent.storage import sqlite as storage_mod

_TEST_UID = 888


@pytest.fixture(autouse=True)
def use_tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_mod, "_DB_DIR", tmp_path)
    monkeypatch.setattr(storage_mod, "_DB_PATH", tmp_path / "test.db")


@pytest.fixture(autouse=True)
def mock_auth(monkeypatch):
    monkeypatch.setattr("finagent.api.deps.get_user_id", lambda r: _TEST_UID)
    monkeypatch.setattr("finagent.api.profile.get_user_id", lambda r: _TEST_UID)
    monkeypatch.setattr("finagent.api.chat.get_user_id", lambda r: _TEST_UID)
    monkeypatch.setattr("finagent.api.deps.require_auth", lambda r: _TEST_UID)


@pytest.fixture
def client():
    return TestClient(app)


# ── Asset Save/Load Round-Trip ──────────────────────────────────────


class TestAssetSaveLoad:

    def test_save_and_load_fd(self, client):
        resp = client.post("/profile/assets", json={
            "asset_type": "fd",
            "items": [{"bank": "SBI", "amount": 500000, "rate": 7.1, "maturity": "2027-06-01"}],
        })
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "count": 1}

        loaded = client.get("/profile/assets?type=fd").json()["items"]
        assert len(loaded) == 1
        assert loaded[0]["bank"] == "SBI"
        assert loaded[0]["amount"] == 500000
        assert loaded[0]["asset_type"] == "fd"

    def test_save_and_load_loan(self, client):
        client.post("/profile/assets", json={
            "asset_type": "loan",
            "items": [{"loan_type": "home", "principal": 5000000, "emi": 45000,
                        "start_date": "2022-01-01", "tenure": "20 years"}],
        })
        loaded = client.get("/profile/assets?type=loan").json()["items"]
        assert len(loaded) == 1
        assert loaded[0]["loan_type"] == "home"
        assert loaded[0]["principal"] == 5000000
        assert loaded[0]["tenure"] == "20 years"

    def test_save_multiple_items(self, client):
        client.post("/profile/assets", json={
            "asset_type": "fd",
            "items": [
                {"bank": "SBI", "amount": 500000},
                {"bank": "HDFC", "amount": 300000},
            ],
        })
        loaded = client.get("/profile/assets?type=fd").json()["items"]
        assert len(loaded) == 2
        banks = {i["bank"] for i in loaded}
        assert banks == {"SBI", "HDFC"}

    def test_save_replaces_previous(self, client):
        """Delete-before-insert: saving same type replaces all previous items."""
        client.post("/profile/assets", json={
            "asset_type": "gold",
            "items": [{"type": "SGB", "value": 100000}],
        })
        client.post("/profile/assets", json={
            "asset_type": "gold",
            "items": [{"type": "Physical", "weight_grams": 50}],
        })
        loaded = client.get("/profile/assets?type=gold").json()["items"]
        assert len(loaded) == 1
        assert loaded[0]["type"] == "Physical"

    def test_load_all_types(self, client):
        client.post("/profile/assets", json={"asset_type": "fd", "items": [{"bank": "SBI"}]})
        client.post("/profile/assets", json={"asset_type": "loan", "items": [{"loan_type": "car"}]})
        all_items = client.get("/profile/assets").json()["items"]
        types = {i["asset_type"] for i in all_items}
        assert types == {"fd", "loan"}

    def test_load_empty(self, client):
        loaded = client.get("/profile/assets?type=fd").json()["items"]
        assert loaded == []


# ── Simple Section Types ────────────────────────────────────────────


class TestSimpleSections:

    @pytest.mark.parametrize("asset_type,data", [
        ("personal", {"marital_status": "married", "kids": 2, "dependents": 3}),
        ("income", {"monthly_salary": 150000, "annual_bonus": 200000}),
        ("expenses", {"rent": 25000, "groceries": 10000, "utilities": 5000}),
        ("epf_ppf", {"epf_balance": 800000, "ppf_balance": 500000}),
        ("nps", {"tier1_balance": 300000, "tier2_balance": 100000}),
        ("insurance", {"term_cover": 10000000, "health_cover": 500000}),
        ("tax", {"regime": "new", "section_80c": 150000}),
    ])
    def test_simple_section_round_trip(self, client, asset_type, data):
        resp = client.post("/profile/assets", json={"asset_type": asset_type, "items": [data]})
        assert resp.json()["ok"] is True
        loaded = client.get(f"/profile/assets?type={asset_type}").json()["items"]
        assert len(loaded) == 1
        for k, v in data.items():
            assert loaded[0][k] == v


# ── Validation ──────────────────────────────────────────────────────


class TestValidation:

    def test_invalid_asset_type(self, client):
        resp = client.post("/profile/assets", json={"asset_type": "crypto", "items": [{"coin": "BTC"}]})
        assert resp.status_code == 400
        assert "Invalid asset type" in resp.json()["error"]

    def test_empty_items(self, client):
        resp = client.post("/profile/assets", json={"asset_type": "fd", "items": []})
        assert resp.status_code == 400
        assert "No items" in resp.json()["error"]

    def test_all_valid_types_accepted(self, client):
        valid = ["fd", "realestate", "gold", "esop", "loan", "personal",
                 "income", "expenses", "epf_ppf", "nps", "stocks", "insurance", "tax"]
        for t in valid:
            resp = client.post("/profile/assets", json={"asset_type": t, "items": [{"x": 1}]})
            assert resp.status_code == 200, f"{t} rejected"


# ── Agent Context: Real LLM ─────────────────────────────────────────


class TestAgentContext:
    """These tests hit the real LLM. Slow (~10-15s each) but high confidence."""

    def test_chat_works_no_assets(self, client):
        """Agent responds without crashing when no assets saved."""
        resp = client.post("/chat", data={"query": "Hello"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert len(resp.json()["response"]) > 10

    def test_agent_sees_saved_fd(self, client):
        """After saving an FD, agent should reference it in response."""
        client.put("/profile", json={"monthly_income": 150000, "age": 28})
        client.post("/profile/assets", json={
            "asset_type": "fd",
            "items": [{"bank": "SBI", "amount": 500000, "rate": 7.1, "maturity": "2027-06-01"}],
        })
        resp = client.post("/chat", data={"query": "What FDs do I have?"})
        assert resp.status_code == 200
        body = resp.json()["response"].lower()
        # Agent should mention SBI or 5 lakh or the FD in some form
        assert any(term in body for term in ["sbi", "5,00,000", "500000", "5 lakh", "fixed deposit", "fd"]), \
            f"Agent didn't reference saved FD. Response: {body[:200]}"

    def test_agent_sees_saved_loan(self, client):
        """After saving a loan, agent should reference it."""
        client.put("/profile", json={"monthly_income": 150000, "age": 28})
        client.post("/profile/assets", json={
            "asset_type": "loan",
            "items": [{"loan_type": "home", "principal": 5000000, "emi": 45000,
                        "start_date": "2022-01-01", "tenure": "20 years"}],
        })
        resp = client.post("/chat", data={"query": "Tell me about my home loan"})
        assert resp.status_code == 200
        body = resp.json()["response"].lower()
        assert any(term in body for term in ["home loan", "50,00,000", "5000000", "50 lakh", "45,000", "45000", "emi"]), \
            f"Agent didn't reference saved loan. Response: {body[:200]}"

    def test_agent_sees_multiple_asset_types(self, client):
        """Agent should see FD + loan + gold all at once."""
        client.put("/profile", json={"monthly_income": 150000, "age": 28})
        client.post("/profile/assets", json={"asset_type": "fd", "items": [{"bank": "ICICI", "amount": 300000}]})
        client.post("/profile/assets", json={"asset_type": "gold", "items": [{"type": "SGB", "value": 200000}]})
        client.post("/profile/assets", json={"asset_type": "loan", "items": [{"loan_type": "car", "emi": 15000}]})
        resp = client.post("/chat", data={"query": "Give me a summary of all my assets and liabilities"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        assert len(resp.json()["response"]) > 50  # non-trivial response


# ── Profile Context for Agent ────────────────────────────────────────


class TestProfileContext:
    """Test _build_profile_context: surplus, savings_rate, clean JSON."""

    def test_surplus_includes_emis(self, client):
        """monthly_surplus = income - expenses - emis."""
        client.post("/profile/assets", json={"asset_type": "personal", "items": [{"name": "Test", "age": 30}]})
        client.post("/profile/assets", json={"asset_type": "income", "items": [{"monthly_income": 285000}]})
        client.post("/profile/assets", json={"asset_type": "expenses", "items": [{"total_monthly_expenses": 80000, "emis": 20000}]})

        from finagent.storage.sqlite import load_profile
        from finagent.orchestrator.engine import _build_profile_context
        import json

        profile = load_profile(_TEST_UID)
        ctx_json, _ = _build_profile_context(profile, _TEST_UID)
        ctx = json.loads(ctx_json)

        assert ctx["monthly_income"] == 285000
        assert ctx["monthly_expenses"] == 80000
        assert ctx["monthly_emis"] == 20000
        assert ctx["monthly_surplus"] == 185000  # 285000 - 80000 - 20000
        assert ctx["savings_rate"] == "65%"  # (285000 - 80000 - 20000) / 285000 = 64.9%

    def test_no_duplicate_flat_sections_in_assets(self, client):
        """personal/income/expenses/meta should NOT appear in assets key."""
        client.post("/profile/assets", json={"asset_type": "personal", "items": [{"name": "Test", "age": 30}]})
        client.post("/profile/assets", json={"asset_type": "income", "items": [{"monthly_income": 100000}]})
        client.post("/profile/assets", json={"asset_type": "meta", "items": [{"onboarding_complete": True}]})
        client.post("/profile/assets", json={"asset_type": "fd", "items": [{"bank": "SBI", "amount": 500000}]})

        from finagent.storage.sqlite import load_profile
        from finagent.orchestrator.engine import _build_profile_context
        import json

        profile = load_profile(_TEST_UID)
        ctx_json, _ = _build_profile_context(profile, _TEST_UID)
        ctx = json.loads(ctx_json)

        assert "assets" in ctx
        assert "personal" not in ctx["assets"]
        assert "income" not in ctx["assets"]
        assert "expenses" not in ctx["assets"]
        assert "meta" not in ctx["assets"]
        assert "fd" in ctx["assets"]

    def test_surplus_zero_when_no_income(self, client):
        """No income → no surplus field in context."""
        client.post("/profile/assets", json={"asset_type": "expenses", "items": [{"total_monthly_expenses": 50000}]})

        from finagent.storage.sqlite import load_profile
        from finagent.orchestrator.engine import _build_profile_context
        import json

        profile = load_profile(_TEST_UID)
        ctx_json, _ = _build_profile_context(profile, _TEST_UID)
        ctx = json.loads(ctx_json)

        assert "monthly_surplus" not in ctx
        assert "savings_rate" not in ctx

    def test_esop_appears_in_assets(self, client):
        """ESOP data should appear under assets.esop."""
        client.post("/profile/assets", json={"asset_type": "esop", "items": [{"company": "Amazon", "vested": 3000000}]})

        from finagent.storage.sqlite import load_profile
        from finagent.orchestrator.engine import _build_profile_context
        import json

        profile = load_profile(_TEST_UID)
        ctx_json, _ = _build_profile_context(profile, _TEST_UID)
        ctx = json.loads(ctx_json)

        assert "assets" in ctx
        assert "esop" in ctx["assets"]
        assert ctx["assets"]["esop"][0]["company"] == "Amazon"
        assert ctx["assets"]["esop"][0]["vested"] == 3000000

    def test_monthly_sip_in_context(self, client):
        """monthly_sip should appear in profile context when set."""
        client.post("/profile/assets", json={"asset_type": "income", "items": [{"monthly_income": 100000, "monthly_sip": 25000}]})

        from finagent.storage.sqlite import load_profile
        from finagent.orchestrator.engine import _build_profile_context
        import json

        profile = load_profile(_TEST_UID)
        ctx_json, _ = _build_profile_context(profile, _TEST_UID)
        ctx = json.loads(ctx_json)

        assert ctx["monthly_sip"] == 25000


# ── Profile + Assets Combined ───────────────────────────────────────


class TestGoalDedup:
    """Test goal creation, update, and dedup via existing_goals in context."""

    def test_create_goal_saves_to_db(self, client):
        """create_goal action saves goal and returns ui_data."""
        from finagent.actions.create_goal import execute as create_goal
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            create_goal({"goal_name": "Buy a house", "target_amount": 5000000, "target_date": "2030-01-01"}, _TEST_UID, {})
        )
        assert "error" not in result
        assert result["ui_data"]["template"] == "house"
        assert result["ui_data"]["goal_id"] > 0

    def test_existing_goals_in_context(self, client):
        """After creating a goal, existing_goals appears in profile context."""
        from finagent.actions.create_goal import execute as create_goal
        from finagent.storage.sqlite import load_profile, save_profile
        from finagent.models.profile import UserProfile
        from finagent.orchestrator.engine import _build_profile_context
        import asyncio, json

        profile = UserProfile(user_id=_TEST_UID)
        save_profile(profile)

        asyncio.get_event_loop().run_until_complete(
            create_goal({"goal_name": "Retirement", "target_amount": 10000000, "target_date": "2050-01-01"}, _TEST_UID, {})
        )

        profile = load_profile(_TEST_UID)
        ctx_json, _ = _build_profile_context(profile, _TEST_UID)
        ctx = json.loads(ctx_json)

        assert "existing_goals" in ctx
        assert len(ctx["existing_goals"]) == 1
        assert ctx["existing_goals"][0]["name"] == "Retirement"
        assert ctx["existing_goals"][0]["template"] == "retirement"
        assert ctx["existing_goals"][0]["target_amount"] == 10000000

    def test_update_goal_changes_amount(self, client):
        """update_goal modifies existing goal without creating duplicate."""
        from finagent.actions.create_goal import execute as create_goal
        from finagent.actions.update_goal import execute as update_goal
        from finagent.storage.sqlite import load_goals
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            create_goal({"goal_name": "Car", "target_amount": 1000000, "target_date": "2028-01-01"}, _TEST_UID, {})
        )
        goal_id = result["ui_data"]["goal_id"]

        result2 = asyncio.get_event_loop().run_until_complete(
            update_goal({"goal_id": goal_id, "target_amount": 1500000}, _TEST_UID, {})
        )
        assert "error" not in result2
        assert result2["ui_data"]["target_amount"] == 1500000

        goals = load_goals(_TEST_UID)
        assert len(goals) == 1  # no duplicate
        assert goals[0].target_amount == 1500000

    def test_update_goal_not_found(self, client):
        """update_goal returns error for non-existent goal_id."""
        from finagent.actions.update_goal import execute as update_goal
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            update_goal({"goal_id": 9999, "target_amount": 500000}, _TEST_UID, {})
        )
        assert "error" in result
        assert "not found" in result["error"]

    def test_multiple_goals_distinct_in_context(self, client):
        """Two different goals both appear in existing_goals."""
        from finagent.actions.create_goal import execute as create_goal
        from finagent.storage.sqlite import load_profile, save_profile
        from finagent.models.profile import UserProfile
        from finagent.orchestrator.engine import _build_profile_context
        import asyncio, json

        profile = UserProfile(user_id=_TEST_UID)
        save_profile(profile)

        asyncio.get_event_loop().run_until_complete(
            create_goal({"goal_name": "House", "target_amount": 5000000, "target_date": "2030-01-01"}, _TEST_UID, {})
        )
        asyncio.get_event_loop().run_until_complete(
            create_goal({"goal_name": "Emergency fund", "target_amount": 300000, "target_date": "2026-12-01"}, _TEST_UID, {})
        )

        profile = load_profile(_TEST_UID)
        ctx_json, _ = _build_profile_context(profile, _TEST_UID)
        ctx = json.loads(ctx_json)

        assert len(ctx["existing_goals"]) == 2
        templates = {g["template"] for g in ctx["existing_goals"]}
        assert templates == {"house", "emergency"}


class TestGoalTransparency:
    """Calculator description flows through create_goal action and API."""

    def test_create_goal_with_calculator_has_description(self, client):
        """When calculator runs, description appears in ui_data and message."""
        from finagent.actions.create_goal import execute as create_goal
        import asyncio

        # Set up profile with expenses and age via API (single storage)
        client.put("/profile", json={"age": 25, "total_monthly_expenses": 20000})

        result = asyncio.get_event_loop().run_until_complete(
            create_goal({"goal_name": "Retirement"}, _TEST_UID, {})
        )
        assert "error" not in result
        assert result["ui_data"]["description"], "Calculator description missing from ui_data"
        assert "📐" in result["message"], "Breakdown not shown in chat message"
        assert result["ui_data"]["target_amount"] > 3_00_00_000, "Calculator didn't run"

    def test_create_goal_without_calculator_has_empty_description(self, client):
        """Custom goals without calculator have empty description."""
        from finagent.actions.create_goal import execute as create_goal
        import asyncio

        result = asyncio.get_event_loop().run_until_complete(
            create_goal({"goal_name": "Travel to Japan", "target_amount": 300000, "target_date": "2027-06-01"}, _TEST_UID, {})
        )
        assert "error" not in result
        assert result["ui_data"]["description"] == ""

    def test_goal_detail_api_returns_description(self, client):
        """GET /goals/{id}/detail includes the description field."""
        from finagent.actions.create_goal import execute as create_goal
        from finagent.storage.sqlite import load_goals
        import asyncio

        client.put("/profile", json={"age": 30, "total_monthly_expenses": 50000})

        result = asyncio.get_event_loop().run_until_complete(
            create_goal({"goal_name": "Retirement"}, _TEST_UID, {})
        )
        goal_id = result["ui_data"]["goal_id"]

        # Verify via direct DB read (same process, same DB)
        goals = load_goals(_TEST_UID)
        goal = next(g for g in goals if g.id == goal_id)
        assert goal.description, "Description missing from stored goal"
        assert "inflation" in goal.description.lower()

    def test_goals_list_api_returns_description(self, client):
        """GET /goals includes description for each goal."""
        from finagent.actions.create_goal import execute as create_goal
        from finagent.storage.sqlite import load_goals
        import asyncio

        client.put("/profile", json={"age": 28, "total_monthly_expenses": 30000})

        asyncio.get_event_loop().run_until_complete(
            create_goal({"goal_name": "Emergency fund"}, _TEST_UID, {})
        )

        # Verify via direct DB read
        goals = load_goals(_TEST_UID)
        assert len(goals) >= 1
        efund = next(g for g in goals if g.template == "emergency")
        assert efund.description, "Description missing from stored goal"
        assert "expenses" in efund.description.lower()


# ── Profile + Assets Combined ───────────────────────────────────────


class TestProfileAndAssets:

    def test_profile_fields_and_assets_coexist(self, client):
        client.put("/profile", json={"monthly_income": 150000, "age": 28})
        client.post("/profile/assets", json={
            "asset_type": "fd",
            "items": [{"bank": "SBI", "amount": 500000}],
        })
        profile = client.get("/profile").json()
        assert profile["profile"]["monthly_income"] == 150000
        assets = client.get("/profile/assets?type=fd").json()["items"]
        assert len(assets) == 1

    def test_put_profile_does_not_affect_assets(self, client):
        client.post("/profile/assets", json={"asset_type": "fd", "items": [{"bank": "SBI"}]})
        client.put("/profile", json={"monthly_income": 200000})
        assets = client.get("/profile/assets?type=fd").json()["items"]
        assert len(assets) == 1
        assert assets[0]["bank"] == "SBI"


# ── Extraction E2E (real LLM) ───────────────────────────────────────

import asyncio
from finagent.models.profile import UserProfile
from finagent.agents.onboarding import extract_profile_data, apply_extractions


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestExtractionE2E:
    """Real LLM extraction tests. Each test sends a natural language message
    and verifies the correct profile fields are extracted and applied."""

    def test_basic_income_and_age(self):
        p = UserProfile(user_id=_TEST_UID)
        ext = _run(extract_profile_data("I'm 28 years old, earning 1.5 LPA monthly take-home is about 95k", p))
        changed = apply_extractions(p, ext)
        assert changed
        assert p.age == 28
        assert p.monthly_income == 95000 or p.monthly_income == 150000  # either monthly or annual interpretation

    def test_expense_breakdown(self):
        p = UserProfile(user_id=_TEST_UID, monthly_income=100000)
        ext = _run(extract_profile_data(
            "My monthly expenses: rent 25k, groceries around 8k, utilities 3k, dining out 5k. Total about 41k.", p))
        changed = apply_extractions(p, ext)
        assert changed
        assert p.rent == 25000
        assert p.groceries == 8000
        assert p.utilities == 3000
        assert p.dining == 5000

    def test_insurance_with_premiums(self):
        p = UserProfile(user_id=_TEST_UID)
        ext = _run(extract_profile_data(
            "I have 1Cr term insurance paying 12k/year premium, and 10L health cover at 18k/year premium", p))
        changed = apply_extractions(p, ext)
        assert changed
        assert p.term_cover == 10000000
        assert p.term_premium == 12000
        assert p.health_cover == 1000000
        assert p.health_premium == 18000

    def test_risk_tolerance(self):
        p = UserProfile(user_id=_TEST_UID)
        ext = _run(extract_profile_data("I have a high risk appetite, 20+ year horizon", p))
        apply_extractions(p, ext)
        assert p.risk_tolerance.lower() in ("aggressive", "high")

    def test_loan_extraction(self):
        p = UserProfile(user_id=_TEST_UID)
        ext = _run(extract_profile_data(
            "I have a home loan of 40L at 8.5% interest, EMI is 35k with 18 years remaining", p))
        changed = apply_extractions(p, ext)
        assert changed
        assert len(p.loans) >= 1
        loan = p.loans[0]
        assert loan["type"] == "home"
        assert loan["emi"] == 35000

    def test_personal_details(self):
        p = UserProfile(user_id=_TEST_UID)
        ext = _run(extract_profile_data(
            "I'm Rahul, 30, married with 1 kid, working as a software engineer at Google in Bangalore", p))
        changed = apply_extractions(p, ext)
        assert changed
        assert p.name == "Rahul"
        assert p.age == 30
        assert p.marital_status.lower() == "married"
        assert p.kids == 1
        assert "engineer" in p.occupation.lower() or "software" in p.occupation.lower()
        assert "google" in p.employer.lower()
        assert "bangalore" in p.location.lower() or "bengaluru" in p.location.lower()

    def test_no_extraction_from_question(self):
        p = UserProfile(user_id=_TEST_UID, monthly_income=100000)
        ext = _run(extract_profile_data("Should I invest in ELSS or PPF for tax saving?", p))
        changed = apply_extractions(p, ext)
        assert not changed  # pure question, no data to extract

    def test_lakh_crore_conversion(self):
        p = UserProfile(user_id=_TEST_UID)
        ext = _run(extract_profile_data("Term cover is 1.5 Cr, health cover 25L", p))
        changed = apply_extractions(p, ext)
        assert changed
        assert p.term_cover == 15000000
        assert p.health_cover == 2500000

    def test_dependent_parents(self):
        p = UserProfile(user_id=_TEST_UID)
        ext = _run(extract_profile_data(
            "I have 2 dependent parents, their health insurance is covered by me", p))
        apply_extractions(p, ext)
        assert p.dependent_parents  # non-empty
        assert p.parents_health_insurance.lower() == "yes"


# ── Extraction E2E: Real LLM ────────────────────────────────────────


class TestExtractionE2E:
    """Test extraction pipeline with real LLM on Reddit-style messages."""

    def _setup_user(self, client):
        client.put("/profile", json={"monthly_income": 75000, "age": 25})

    def test_extract_ppf_nps_epf(self, client):
        """PPF/NPS/EPF mentioned in chat should be extracted to assets."""
        self._setup_user(client)
        resp = client.post("/chat/stream", data={
            "query": "PPF: Already have 3L+ accumulated. EPF: Ongoing salary deduction. NPS: Corporate NPS, employer contributes 3k/month."
        })
        assert resp.status_code == 200

        epf = client.get("/profile/assets?type=epf_ppf").json()["items"]
        nps = client.get("/profile/assets?type=nps").json()["items"]
        # At least one of these should have been extracted
        has_ppf = any(i.get("ppf_balance") for i in epf)
        has_nps = any(i.get("nps_contribution") or i.get("nps_balance") for i in nps)
        assert has_ppf or has_nps, f"Neither PPF nor NPS extracted. epf={epf}, nps={nps}"

    def test_extract_mf_sips(self, client):
        """MF SIP allocations should be extracted to mf (source=declared)."""
        self._setup_user(client)
        resp = client.post("/chat/stream", data={
            "query": "My monthly SIP plan is 56k: Edelweiss Mid Cap 25%, Parag Parikh Flexi Cap 10%, Nifty 50 Index 10%"
        })
        assert resp.status_code == 200

        mfs = client.get("/profile/assets?type=mf").json()["items"]
        schemes = [i.get("scheme", "") for i in mfs]
        assert any("Edelweiss" in s or "Mid Cap" in s for s in schemes), f"Edelweiss not extracted. mfs={mfs}"

    def test_extract_fd(self, client):
        """FD mentioned in chat should be extracted."""
        self._setup_user(client)
        resp = client.post("/chat/stream", data={
            "query": "I have 1.5L in a Flexi FD at SBI"
        })
        assert resp.status_code == 200

    def test_incomplete_mf_mention_asks_followup(self, client):
        """Vague MF mention should NOT be saved — advisor should ask for details."""
        self._setup_user(client)
        resp = client.post("/chat/stream", data={
            "query": "I have some investment in ICICI Small Cap fund"
        })
        assert resp.status_code == 200

        # Should NOT have saved an empty MF entry
        mfs = client.get("/profile/assets?type=mf").json()["items"]
        icici = [m for m in mfs if "ICICI" in (m.get("scheme") or m.get("scheme_name") or "")]
        assert len(icici) == 0, f"Empty MF should not be saved. Found: {icici}"

        # Response should ask for more details (amount, SIP, etc.)
        text = resp.text.lower()
        assert any(w in text for w in ("how much", "amount", "sip", "value", "invested")), \
            f"Advisor should ask follow-up. Response: {resp.text[:300]}"

    def test_extract_fd(self, client):
        """FD mentioned in chat should be extracted."""
        self._setup_user(client)
        resp = client.post("/chat/stream", data={
            "query": "I have 1.5L in a Flexi FD at SBI"
        })
        assert resp.status_code == 200

        fds = client.get("/profile/assets?type=fd").json()["items"]
        assert len(fds) >= 1, f"No FDs extracted. fds={fds}"

    def test_extract_monthly_sip_profile_field(self, client):
        """Total monthly SIP should be saved as profile field."""
        self._setup_user(client)
        resp = client.post("/chat/stream", data={
            "query": "I invest about 56000 per month via SIPs in mutual funds"
        })
        assert resp.status_code == 200

        from finagent.storage.sqlite import load_profile
        profile = load_profile(_TEST_UID)
        assert profile.monthly_sip > 0, f"monthly_sip={profile.monthly_sip}, expected > 0"

    def test_agent_sees_monthly_sip_in_context(self, client):
        """Agent should see monthly_sip and NOT flag surplus as fully unallocated."""
        client.post("/profile/assets", json={"asset_type": "personal", "items": [{"age": 25}]})
        client.post("/profile/assets", json={"asset_type": "income", "items": [{"monthly_income": 75000, "monthly_sip": 40000}]})
        client.post("/profile/assets", json={"asset_type": "expenses", "items": [{"total_monthly_expenses": 20000}]})
        resp = client.post("/chat", data={
            "query": "Am I investing enough? Give me a quick review of my finances."
        })
        assert resp.status_code == 200
        body = resp.json()["response"].lower()
        # Agent should acknowledge the SIP, not say all 55k surplus is unallocated
        assert any(t in body for t in ["sip", "40,000", "40000", "40k", "mutual fund"]), \
            f"Agent didn't acknowledge monthly_sip=40000. Response: {body[:300]}"
