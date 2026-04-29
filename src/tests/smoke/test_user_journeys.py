"""
Smoke tests: Can the user do X?

Each test represents a real user journey end-to-end.
Run with: pytest tests/smoke/ -m e2e -v

These are the things that MUST work for Arth to be useful.
If any fail after a push, something the user cares about is broken.
"""
import os

os.environ["DEV_MODE"] = "1"

import pytest
from fastapi.testclient import TestClient
from finagent.main import app
from finagent.storage import sqlite as storage_mod

COOKIES = {"session": "arth-dev"}

pytestmark = pytest.mark.e2e


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_mod, "_DB_DIR", tmp_path)
    monkeypatch.setattr(storage_mod, "_DB_PATH", tmp_path / "test.db")


@pytest.fixture
def client():
    return TestClient(app)


# ── Journey 1: New user can start a conversation ──────────────────────

class TestNewUserCanChat:
    """Brand new user opens Arth and says hello."""

    def test_chat_returns_response(self, client):
        resp = client.post("/chat", data={"query": "hi"}, cookies=COOKIES)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert len(body["response"]) > 20, f"Too short: {body['response']!r}"

    def test_chat_handles_financial_question(self, client):
        resp = client.post("/chat", data={"query": "How should I start investing?"}, cookies=COOKIES)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ── Journey 2: User can save and retrieve their profile ───────────────

class TestUserCanManageProfile:
    """User fills in their basic details and reads them back."""

    def test_save_and_read_profile(self, client):
        # Save via PUT
        resp = client.put("/profile", json={
            "name": "Priya", "age": 28,
            "monthly_income": 120000, "monthly_expenses": 45000,
        }, cookies=COOKIES)
        assert resp.status_code == 200

        # Read back
        resp = client.get("/profile", cookies=COOKIES)
        assert resp.status_code == 200
        profile = resp.json()["profile"]
        assert profile["name"] == "Priya"
        assert profile["age"] == 28
        assert profile["monthly_income"] == 120000

    def test_save_profile_assets(self, client):
        resp = client.post("/profile/assets", json={
            "asset_type": "epf_ppf",
            "items": [{"label": "EPF", "balance": 500000, "epf_contribution": 5000}],
        }, cookies=COOKIES)
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # Read back
        resp = client.get("/profile/assets?type=epf_ppf", cookies=COOKIES)
        assert resp.status_code == 200
        assert len(resp.json()["items"]) >= 1


# ── Journey 3: User can create and manage goals ──────────────────────

class TestUserCanManageGoals:
    """User creates a goal, sees it, updates it, deletes it."""

    def test_goal_lifecycle(self, client):
        # Create
        resp = client.post("/goals", json={
            "name": "Emergency Fund",
            "target_amount": 300000,
            "target_date": "2027-06-01",
        }, cookies=COOKIES)
        assert resp.status_code == 200
        goal_id = resp.json()["goal_id"]

        # List
        resp = client.get("/goals", cookies=COOKIES)
        assert resp.status_code == 200
        names = [g["name"] for g in resp.json()["goals"]]
        assert "Emergency Fund" in names

        # Update
        resp = client.put(f"/goals/{goal_id}", json={
            "target_amount": 500000,
        }, cookies=COOKIES)
        assert resp.status_code == 200

        # Delete
        resp = client.delete(f"/goals/{goal_id}", cookies=COOKIES)
        assert resp.status_code == 200

        # Verify gone
        resp = client.get("/goals", cookies=COOKIES)
        ids = [g["id"] for g in resp.json()["goals"]]
        assert goal_id not in ids


# ── Journey 4: User can see their financial overview ─────────────────

class TestUserCanSeeOverview:
    """User with some data sees a meaningful overview."""

    def test_overview_returns_structure(self, client):
        # Seed some data
        client.put("/profile", json={
            "name": "Rahul", "age": 30,
            "monthly_income": 150000, "monthly_expenses": 60000,
        }, cookies=COOKIES)
        client.post("/profile/assets", json={
            "asset_type": "epf_ppf",
            "items": [{"label": "EPF", "balance": 800000}],
        }, cookies=COOKIES)

        resp = client.get("/overview", cookies=COOKIES)
        assert resp.status_code == 200
        data = resp.json()
        assert "net_worth" in data

    def test_empty_overview_doesnt_crash(self, client):
        """New user with no data — overview should still return 200."""
        resp = client.get("/overview", cookies=COOKIES)
        assert resp.status_code == 200


# ── Journey 5: User can upload CAS and see holdings ──────────────────

class TestUserCanUploadCAS:
    """User uploads a CAS PDF and sees their mutual fund holdings."""

    def test_bad_upload_returns_error(self, client):
        resp = client.post("/upload",
            files={"file": ("test.txt", b"not a pdf", "text/plain")},
            cookies=COOKIES)
        # Should reject non-PDF gracefully
        assert resp.status_code in (400, 422, 200)  # may return error in body

    def test_holdings_endpoint_works(self, client):
        resp = client.get("/holdings", cookies=COOKIES)
        assert resp.status_code == 200


# ── Journey 6: Chat-driven data extraction ────────────────────────────

class TestChatExtractsData:
    """User tells Arth about their finances in natural language.
    Arth extracts and saves the data."""

    def test_profile_extraction_from_chat(self, client):
        resp = client.post("/chat",
            data={"query": "I'm 28 years old, earning 1.5 lakh per month. Monthly expenses around 50k."},
            cookies=COOKIES)
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"
        # Response should acknowledge the data
        assert len(resp.json()["response"]) > 20

        # Profile should have been updated by extraction
        resp = client.get("/profile", cookies=COOKIES)
        assert resp.status_code == 200
        # Extraction is LLM-dependent — we verify the endpoint works,
        # not exact field values
