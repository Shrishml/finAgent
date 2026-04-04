"""Tests for Session 2: CAMS connector, SQLite storage, MF agent."""
import json
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import patch, AsyncMock

from finagent.connectors.cams import CAMSConnector, _parse_date, _safe_float
from finagent.storage import sqlite as storage_mod
from finagent.models.mf import MFHolding, MFTransaction
from finagent.agents.mf import MFAgent


# --- CAMS Connector helpers ---

class TestCAMSHelpers:
    def test_parse_date_string(self):
        assert _parse_date("15-Jan-2026") == date(2026, 1, 15)

    def test_parse_date_slash_format(self):
        assert _parse_date("15/01/2026") == date(2026, 1, 15)

    def test_parse_date_iso(self):
        assert _parse_date("2026-01-15") == date(2026, 1, 15)

    def test_parse_date_invalid(self):
        assert _parse_date("garbage") == date(1970, 1, 1)

    def test_parse_date_empty(self):
        assert _parse_date("") == date(1970, 1, 1)

    def test_safe_float_none(self):
        assert _safe_float(None) == 0.0

    def test_safe_float_string(self):
        assert _safe_float("123.45") == 123.45

    def test_safe_float_invalid(self):
        assert _safe_float("N/A") == 0.0


class TestCAMSConnector:
    def test_detect_pdf(self, tmp_path):
        c = CAMSConnector()
        assert c.detect(tmp_path / "test.pdf") is True
        assert c.detect(tmp_path / "test.csv") is False

    def test_target_domain(self):
        assert CAMSConnector().target_domain() == "mf"

    def test_parse_maps_fields(self):
        """Test that casparser output is correctly mapped to MFHolding."""
        fake_data = {
            "folios": [{
                "folio": "12345",
                "amc": "Axis Mutual Fund",
                "schemes": [{
                    "scheme": "Axis Bluechip Fund - Direct Growth",
                    "isin": "INF846K01DP8",
                    "amfi": "120503",
                    "rta": "CAMS",
                    "open": 100.5,
                    "close": 45.67,
                    "transactions": [
                        {"date": "15-Jan-2026", "description": "SIP", "amount": 5000,
                         "units": 10.5, "nav": 45.67, "balance": 100.5, "type": "PURCHASE"},
                    ],
                }],
            }],
        }
        with patch("casparser.read_cas_pdf", return_value=fake_data):
            c = CAMSConnector()
            holdings = c.parse(Path("fake.pdf"), "password")

        assert len(holdings) == 1
        h = holdings[0]
        assert h.scheme_name == "Axis Bluechip Fund - Direct Growth"
        assert h.folio == "12345"
        assert h.amc == "Axis Mutual Fund"
        assert h.isin == "INF846K01DP8"
        assert h.plan == "direct"
        assert h.units == 100.5
        assert h.nav == 45.67
        assert len(h.transactions) == 1
        assert h.transactions[0].amount == 5000


# --- SQLite Storage ---

class TestSQLiteStorage:
    @pytest.fixture(autouse=True)
    def use_tmp_db(self, tmp_path, monkeypatch):
        monkeypatch.setattr(storage_mod, "_DB_DIR", tmp_path)
        monkeypatch.setattr(storage_mod, "_DB_PATH", tmp_path / "test.db")

    def _make_holding(self, name="Test Fund", folio="F1"):
        return MFHolding(scheme_name=name, folio=folio, amc="Test AMC",
                         current_value=50000, expense_ratio=0.01)

    def test_save_and_load(self):
        h = self._make_holding()
        storage_mod.save_holdings([h])
        loaded = storage_mod.load_holdings()
        assert len(loaded) == 1
        assert loaded[0].scheme_name == "Test Fund"
        assert loaded[0].current_value == 50000

    def test_upsert_replaces(self):
        h1 = self._make_holding(name="Fund A", folio="F1")
        storage_mod.save_holdings([h1])
        h2 = MFHolding(scheme_name="Fund A", folio="F1", amc="Test", current_value=60000)
        storage_mod.save_holdings([h2])
        loaded = storage_mod.load_holdings()
        assert len(loaded) == 1
        assert loaded[0].current_value == 60000

    def test_multiple_holdings(self):
        storage_mod.save_holdings([
            self._make_holding("Fund A", "F1"),
            self._make_holding("Fund B", "F2"),
        ])
        assert len(storage_mod.load_holdings()) == 2

    def test_clear(self):
        storage_mod.save_holdings([self._make_holding()])
        storage_mod.clear_holdings()
        assert len(storage_mod.load_holdings()) == 0

    def test_nav_cache(self):
        storage_mod.save_nav_cache("120503", 45.67, "Axis Bluechip")
        assert storage_mod.get_cached_nav("120503") == 45.67

    def test_nav_cache_miss(self):
        assert storage_mod.get_cached_nav("nonexistent") is None


# --- MF Agent ---

class TestMFAgent:
    def _make_holdings(self):
        return [
            MFHolding(scheme_name="Fund A - Direct Growth", folio="F1", amc="AMC1",
                       plan="direct", current_value=100000, invested_value=80000,
                       expense_ratio=0.005, annual_expense=500, xirr=0.12),
            MFHolding(scheme_name="Fund B - Regular Growth", folio="F2", amc="AMC2",
                       plan="regular", current_value=50000, invested_value=45000,
                       expense_ratio=0.018, annual_expense=900, xirr=0.08),
        ]

    def test_compute_analysis_totals(self):
        agent = MFAgent()
        result = agent._compute_analysis(self._make_holdings())
        assert "150,000" in result     # total value
        assert "1,400" in result       # total expense
        assert "Schemes: 2" in result  # number of schemes

    def test_compute_analysis_flags_regular(self):
        agent = MFAgent()
        result = agent._compute_analysis(self._make_holdings())
        assert "regular plan" in result.lower()
        assert "direct" in result.lower()

    def test_compute_analysis_flags_high_expense(self):
        agent = MFAgent()
        result = agent._compute_analysis(self._make_holdings())
        assert "expense ratio" in result.lower()

    def test_get_summaries(self):
        agent = MFAgent()
        summaries = agent.get_summaries(self._make_holdings())
        assert len(summaries) == 2
        assert summaries[0].product_type == "mutual_fund"

    def test_analyze_no_data(self):
        import asyncio
        agent = MFAgent()
        result = asyncio.get_event_loop().run_until_complete(agent.analyze("test", []))
        assert "upload" in result.lower()

    def test_supported_connectors(self):
        assert "cams" in MFAgent().supported_connectors()
