"""Unit tests for core models and LLM layer."""
import json
import pytest

from finagent.models import FinancialSummary, MFHolding, MFTransaction
from finagent.config import get_config
from finagent.llm.kiro import KiroCLIProvider
from finagent.connectors.base import Connector, ConnectorRegistry
from pathlib import Path
from datetime import date


# --- FinancialSummary ---

class TestFinancialSummary:
    def test_defaults(self):
        s = FinancialSummary(product_type="mf", product_name="Test", annual_cost=0, current_value=0)
        assert s.currency == "INR"
        assert s.tax_sections == []
        assert s.risk_tags == []
        assert s.liquidity == "unknown"

    def test_metadata(self):
        s = FinancialSummary(
            product_type="mf", product_name="Test", annual_cost=100,
            current_value=10000, metadata={"xirr": 0.12}
        )
        assert s.metadata["xirr"] == 0.12


# --- MFHolding ---

class TestMFHolding:
    def _make_holding(self, **overrides):
        defaults = dict(
            scheme_name="Axis Bluechip Fund - Direct Growth",
            folio="123456",
            amc="Axis",
            current_value=100000,
            expense_ratio=0.015,
            annual_expense=1500,
            plan="direct",
        )
        defaults.update(overrides)
        return MFHolding(**defaults)

    def test_to_summary_basic(self):
        h = self._make_holding()
        s = h.to_summary()
        assert s.product_type == "mutual_fund"
        assert s.product_name == "Axis Bluechip Fund - Direct Growth"
        assert s.annual_cost == 1500
        assert s.current_value == 100000

    def test_to_summary_high_expense_tag(self):
        h = self._make_holding(expense_ratio=0.015)
        s = h.to_summary()
        assert "high_expense" in s.risk_tags

    def test_to_summary_low_expense_no_tag(self):
        h = self._make_holding(expense_ratio=0.005)
        s = h.to_summary()
        assert "high_expense" not in s.risk_tags

    def test_to_summary_regular_plan_tag(self):
        h = self._make_holding(plan="regular")
        s = h.to_summary()
        assert "regular_plan" in s.risk_tags

    def test_to_summary_elss_locked(self):
        h = self._make_holding(tax_section="80C")
        s = h.to_summary()
        assert s.tax_sections == ["80C"]
        assert s.liquidity == "locked_3yr"

    def test_to_summary_non_elss_liquid(self):
        h = self._make_holding(tax_section="")
        s = h.to_summary()
        assert s.tax_sections == []
        assert s.liquidity == "t+3"

    def test_to_summary_metadata(self):
        h = self._make_holding(xirr=0.12, expense_ratio=0.01, folio="F1")
        s = h.to_summary()
        assert s.metadata["xirr"] == 0.12
        assert s.metadata["folio"] == "F1"


class TestMFTransaction:
    def test_creation(self):
        t = MFTransaction(date=date(2026, 1, 15), description="SIP", amount=5000, units=50.5, type="PURCHASE")
        assert t.amount == 5000
        assert t.type == "PURCHASE"


# --- Config ---

class TestConfig:
    def test_defaults_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("finagent.config._config", None)
        monkeypatch.setattr("finagent.config._SRC_DIR", tmp_path)
        cfg = get_config()
        assert cfg["llm"]["default"] == "kiro"
        assert cfg["server"]["port"] == 8000
        # Reset global
        monkeypatch.setattr("finagent.config._config", None)

    def test_json_fallback(self, tmp_path, monkeypatch):
        monkeypatch.setattr("finagent.config._config", None)
        monkeypatch.setattr("finagent.config._SRC_DIR", tmp_path)
        (tmp_path / "config.json").write_text(json.dumps({"llm": {"default": "test"}}))
        cfg = get_config()
        assert cfg["llm"]["default"] == "test"
        monkeypatch.setattr("finagent.config._config", None)


# --- KiroCLIProvider response extraction ---

class TestKiroExtractResponse:
    def setup_method(self):
        self.provider = KiroCLIProvider()

    def test_strips_plain_text(self):
        raw = "  \n  Hello world  \n  "
        assert self.provider._extract_response(raw, json_mode=False) == "Hello world"

    def test_strips_box_drawing(self):
        raw = "╭──────────────╮\n│ kiro-cli 1.0 │\n╰──────────────╯\nActual response"
        result = self.provider._extract_response(raw, json_mode=False)
        assert "Actual response" in result
        assert "╭" not in result

    def test_json_mode_extracts_object(self):
        raw = 'Here is the result:\n{"domain": "mf", "mode": "analyze"}\nDone.'
        result = self.provider._extract_response(raw, json_mode=True)
        parsed = json.loads(result)
        assert parsed["domain"] == "mf"

    def test_json_mode_extracts_array(self):
        raw = 'Results:\n[{"name": "fund1"}, {"name": "fund2"}]'
        result = self.provider._extract_response(raw, json_mode=True)
        parsed = json.loads(result)
        assert len(parsed) == 2

    def test_json_mode_fallback_to_text(self):
        raw = "No JSON here, just text"
        result = self.provider._extract_response(raw, json_mode=True)
        assert result == "No JSON here, just text"

    def test_strips_ansi_codes(self):
        raw = "\x1b[38;5;141m> \x1b[0mHello \x1b[1mworld\x1b[22m\x1b[0m"
        result = self.provider._extract_response(raw, json_mode=False)
        assert "\x1b" not in result
        assert "Hello" in result
        assert "world" in result


# --- ConnectorRegistry ---

class TestConnectorRegistry:
    def test_no_connector_raises(self, tmp_path):
        registry = ConnectorRegistry()
        with pytest.raises(ValueError, match="No connector can handle"):
            registry.parse(tmp_path / "unknown.xyz")

    def test_dispatches_to_matching_connector(self, tmp_path):
        class FakeConnector(Connector):
            def detect(self, file_path): return file_path.suffix == ".pdf"
            def parse(self, file_path, password=""): return [{"parsed": True}]
            def target_domain(self): return "mf"

        registry = ConnectorRegistry()
        registry.register(FakeConnector())
        pdf = tmp_path / "test.pdf"
        pdf.touch()
        domain, results = registry.parse(pdf)
        assert domain == "mf"
        assert results == [{"parsed": True}]
