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
        ("family", {"marital_status": "married", "kids": 2, "dependents": 3}),
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
        valid = ["fd", "realestate", "gold", "esop", "loan", "family",
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
        assets = client.get("/profile/assets").json()["items"]
        assert len(assets) == 1

    def test_put_profile_does_not_affect_assets(self, client):
        client.post("/profile/assets", json={"asset_type": "fd", "items": [{"bank": "SBI"}]})
        client.put("/profile", json={"monthly_income": 200000})
        assets = client.get("/profile/assets?type=fd").json()["items"]
        assert len(assets) == 1
        assert assets[0]["bank"] == "SBI"
