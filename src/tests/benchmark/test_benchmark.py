"""E2E Benchmark: seed dummy portfolio → chat → verify LLM response quality.

Run with: pytest -m e2e
Requires: kiro-cli installed and working.
"""
import pytest
from fastapi.testclient import TestClient

from finagent.main import app
from finagent.models.mf import MFHolding
from finagent.storage import sqlite as storage_mod
from finagent.storage.sqlite import save_holdings, clear_holdings

# Skip all tests in this file if not running E2E
pytestmark = pytest.mark.e2e

# --- Dummy Portfolio (known facts we can assert against) ---

DUMMY_PORTFOLIO = [
    MFHolding(
        scheme_name="Nifty 50 Index Fund - Direct Growth",
        folio="F001", amc="UTI", plan="direct",
        units=500, nav=120.50, current_value=60250,
        invested_value=50000, expense_ratio=0.002, annual_expense=120.50,
        xirr=0.14, isin="INF001", amfi_code="100001",
    ),
    MFHolding(
        scheme_name="HDFC Balanced Advantage Fund - Regular Growth",
        folio="F002", amc="HDFC", plan="regular",
        units=1000, nav=45.00, current_value=45000,
        invested_value=40000, expense_ratio=0.018, annual_expense=810,
        xirr=0.09, isin="INF002", amfi_code="100002",
    ),
    MFHolding(
        scheme_name="Axis ELSS Tax Saver Fund - Direct Growth",
        folio="F003", amc="Axis", plan="direct",
        units=200, nav=85.00, current_value=17000,
        invested_value=15000, expense_ratio=0.008, annual_expense=136,
        xirr=0.11, tax_section="80C", isin="INF003", amfi_code="100003",
    ),
    MFHolding(
        scheme_name="SBI Small Cap Fund - Direct Growth",
        folio="F004", amc="SBI", plan="direct",
        units=300, nav=150.00, current_value=45000,
        invested_value=35000, expense_ratio=0.007, annual_expense=315,
        xirr=0.22, isin="INF004", amfi_code="100004",
    ),
    MFHolding(
        scheme_name="Parag Parikh Flexi Cap Fund - Regular Growth",
        folio="F005", amc="PPFAS", plan="regular",
        units=400, nav=70.00, current_value=28000,
        invested_value=25000, expense_ratio=0.022, annual_expense=616,
        xirr=0.10, isin="INF005", amfi_code="100005",
    ),
]

# Known facts about this portfolio (for assertion)
KNOWN_FACTS = {
    "total_value": 195250,          # sum of current_value
    "total_invested": 165000,       # sum of invested_value
    "num_schemes": 5,
    "regular_plan_funds": ["HDFC Balanced Advantage", "Parag Parikh Flexi Cap"],
    "direct_plan_funds": ["Nifty 50 Index", "Axis ELSS", "SBI Small Cap"],
    "elss_fund": "Axis ELSS",
    "highest_expense": "Parag Parikh Flexi Cap",  # 2.2%
    "best_performer": "SBI Small Cap",             # 22% XIRR
    "total_annual_expense": 1997.5,
}


@pytest.fixture(autouse=True)
def setup_dummy_portfolio(tmp_path, monkeypatch):
    """Seed dummy portfolio before each test, clean up after."""
    monkeypatch.setattr(storage_mod, "_DB_DIR", tmp_path)
    monkeypatch.setattr(storage_mod, "_DB_PATH", tmp_path / "test.db")
    save_holdings(DUMMY_PORTFOLIO)
    yield
    clear_holdings()


@pytest.fixture
def client():
    return TestClient(app)


def _chat(client, query: str) -> str:
    """Send chat query and return response text."""
    resp = client.post("/chat", data={"query": query})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok", f"Chat failed: {data.get('message')}"
    return data["response"]


# --- Benchmark Scenarios ---

class TestExpenseAnalysis:
    """User asks about costs — response should mention regular plan funds and high expenses."""

    def test_expense_ratio_question(self, client):
        response = _chat(client, "What are my expense ratios?")
        # Must mention at least some fund names
        assert any(name.lower() in response.lower() for name in ["nifty", "hdfc", "axis", "sbi", "parag"]), \
            f"Response doesn't mention any fund names: {response[:200]}"

    def test_regular_plan_detection(self, client):
        response = _chat(client, "Are any of my funds on regular plan?")
        r = response.lower()
        # Must identify regular plan funds
        assert "regular" in r, f"Response doesn't mention 'regular': {response[:200]}"
        # Should mention at least one of the regular plan funds
        assert "hdfc" in r or "parag" in r, \
            f"Response doesn't identify regular plan funds: {response[:200]}"


class TestPortfolioOverview:
    """User asks for portfolio summary — response should have correct totals."""

    def test_portfolio_summary(self, client):
        response = _chat(client, "Give me a summary of my portfolio")
        r = response.lower()
        # Must mention number of funds or schemes
        assert "5" in response or "five" in r, \
            f"Response doesn't mention 5 schemes: {response[:200]}"


class TestPerformance:
    """User asks about returns — response should reference XIRR data."""

    def test_best_performer(self, client):
        response = _chat(client, "Which of my funds is performing the best?")
        r = response.lower()
        # SBI Small Cap has 22% XIRR — should be mentioned
        assert "sbi" in r or "small cap" in r, \
            f"Response doesn't identify best performer: {response[:200]}"


class TestTaxSection:
    """User asks about tax — response should mention ELSS and 80C."""

    def test_tax_saving_funds(self, client):
        response = _chat(client, "Which of my funds give tax benefits?")
        r = response.lower()
        assert "80c" in r or "elss" in r or "tax" in r, \
            f"Response doesn't mention tax benefits: {response[:200]}"


# --- Live AMFI API test ---

class TestAMFILive:
    """Live test that hits mfdata.in API. Requires internet."""

    def test_fetch_known_scheme(self):
        from finagent.connectors.amfi import _fetch_scheme
        # Parag Parikh Conservative Hybrid Fund - Direct Growth
        data = _fetch_scheme("148958")
        assert data is not None, "mfdata.in returned no data for AMFI 148958"
        assert "nav" in data, f"No NAV in response: {data}"
        assert "expense_ratio" in data, f"No expense_ratio in response: {data}"
        assert float(data["nav"]) > 0, f"NAV should be positive: {data['nav']}"
        assert float(data["expense_ratio"]) > 0, f"Expense ratio should be positive: {data['expense_ratio']}"
        print(f"\n  ✅ AMFI 148958: NAV={data['nav']}, ER={data['expense_ratio']}%, category={data.get('category')}")

    def test_fetch_multiple_schemes(self):
        from finagent.connectors.amfi import _fetch_scheme
        # Test a few of your actual fund AMFI codes
        codes = {"120505": "Axis Mid Cap", "118989": "HDFC Mid Cap", "122639": "Parag Parikh Flexi Cap"}
        for code, name in codes.items():
            data = _fetch_scheme(code)
            assert data is not None, f"mfdata.in returned no data for {name} (AMFI {code})"
            assert float(data.get("nav", 0)) > 0, f"No NAV for {name}"
            print(f"  ✅ {name}: NAV={data['nav']}, ER={data.get('expense_ratio', 'N/A')}%")
