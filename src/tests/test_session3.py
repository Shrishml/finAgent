"""Tests for Session 3: router, orchestrator, API."""
import pytest
from unittest.mock import patch, AsyncMock

from finagent.orchestrator.router import _keyword_classify
from finagent.orchestrator.engine import handle_query
from finagent.storage import sqlite as storage_mod
from finagent.models.mf import MFHolding


# --- Keyword Router ---

class TestKeywordClassify:
    def test_mf_analyze(self):
        r = _keyword_classify("What are my expense ratios?")
        assert r["domain"] == "mf"
        assert r["mode"] == "analyze"

    def test_mf_research(self):
        r = _keyword_classify("Find me the best index fund")
        assert r["domain"] == "mf"
        assert r["mode"] == "research"

    def test_insurance(self):
        r = _keyword_classify("Is my health insurance premium too high?")
        assert r["domain"] == "insurance"

    def test_loan(self):
        r = _keyword_classify("Should I prepay my home loan or invest?")
        assert r["domain"] == "loan"
        assert r["mode"] == "cross_domain"

    def test_general(self):
        r = _keyword_classify("Hello, how are you?")
        assert r["domain"] == "general"

    def test_portfolio_keyword(self):
        r = _keyword_classify("Show me my portfolio")
        assert r["domain"] == "mf"

    def test_recommend_mode(self):
        r = _keyword_classify("Recommend a good SIP fund")
        assert r["mode"] == "research"

    def test_suggest_alternative(self):
        r = _keyword_classify("Suggest an alternative to my current fund")
        assert r["domain"] == "mf"
        assert r["mode"] == "research"


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
