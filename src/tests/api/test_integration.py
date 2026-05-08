"""Integration tests: full pipeline upload → store → chat."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path

from fastapi.testclient import TestClient

from finagent.main import app
from finagent.storage import sqlite as storage_mod


@pytest.fixture(autouse=True)
def use_tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_mod, "_DB_DIR", tmp_path)
    monkeypatch.setattr(storage_mod, "_DB_PATH", tmp_path / "test.db")


@pytest.fixture(autouse=True)
def skip_enrichment(monkeypatch):
    monkeypatch.setattr("finagent.api.holdings.enrich_holdings", lambda h: h)


@pytest.fixture(autouse=True)
def mock_auth(monkeypatch):
    monkeypatch.setattr("finagent.api.deps.get_user_id", lambda r: 1)
    monkeypatch.setattr("finagent.api.holdings.get_user_id", lambda r: 1)
    monkeypatch.setattr("finagent.api.chat.get_user_id", lambda r: 1)
    monkeypatch.setattr("finagent.api.deps.require_auth", lambda r: 1)
    monkeypatch.setattr("finagent.api.holdings.require_auth", lambda r: 1)
    monkeypatch.setattr("finagent.api.chat.require_auth", lambda r: 1)


@pytest.fixture
def client():
    return TestClient(app)


def _mock_casparser_data():
    """Fake casparser output matching real pydantic structure."""
    m = MagicMock
    tx1 = m(date="15-Jan-2026", description="SIP", amount=5000, units=100.5, nav=49.75, balance=100.5, type="PURCHASE", dividend_rate=None)
    tx2 = m(date="15-Feb-2026", description="SIP", amount=5000, units=98.2, nav=50.92, balance=198.7, type="PURCHASE", dividend_rate=None)
    valuation = m(nav=51.23, value=10179.4, cost=10000.0, date=None)
    scheme = m(scheme="Test Fund - Direct Growth", isin="INF123", amfi="999999",
               rta="CAMS", open=0, close=198.7, close_calculated=198.7,
               valuation=valuation, transactions=[tx1, tx2],
               advisor=None, rta_code=None, type=None, nominees=None)
    folio = m(folio="F12345", amc="Test AMC", schemes=[scheme], PAN=None, KYC=None, PANKYC=None)
    cas_data = m(folios=[folio], cas_type="DETAILED", file_type="CAMS",
                 statement_period=m(from_date="2025-01-01", to_date="2026-03-31"),
                 investor_info=m(name="Test User", email="test@test.com", mobile="", address=""))
    return cas_data


class TestChatPipeline:
    def test_chat_with_no_data(self, client):
        with patch("finagent.orchestrator.engine.classify_intent", new_callable=AsyncMock,
                   return_value={"domain": "mf", "mode": "analyze"}):
            resp = client.post("/chat", data={"query": "What are my expense ratios?"})
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["response"]) > 0  # advisor responds (no longer routes to MF agent)

    def test_upload_bad_file_returns_error(self, client, tmp_path):
        txt = tmp_path / "test.txt"
        txt.write_text("not a pdf")
        resp = client.post("/upload", files={"file": ("test.txt", txt.read_bytes(), "text/plain")}, data={"password": ""})
        assert resp.status_code == 400
