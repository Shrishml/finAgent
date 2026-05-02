"""Overview page contract tests: verify net worth, goals, cash flow, nudges
for different user personas.

Each persona represents a real user archetype. Tests verify the overview
API computes correct numbers — not just "doesn't crash" but "shows right data".
"""
import pytest
from datetime import date, timedelta

from finagent.models.profile import UserProfile
from finagent.models.goal import Goal
from finagent.models.mf import MFHolding
import finagent.storage as store


@pytest.fixture
async def new_user_uid():
    return await store.get_or_create_user("new-user", "new@test.com", "New")


@pytest.mark.asyncio
class TestOverviewNewUser:
    """Brand new user — no data at all. Overview should not crash."""

    async def test_net_worth_is_zero(self, new_user_uid):
        from finagent.api.overview import _net_worth
        nw = await _net_worth(new_user_uid, [])
        assert nw["total"] == 0
        assert nw["total_assets"] == 0
        assert nw["total_liabilities"] == 0

    async def test_cash_flow_is_none_without_profile(self):
        from finagent.api.overview import _cash_flow
        assert _cash_flow(None) is None

    async def test_goal_summaries_empty(self, new_user_uid):
        from finagent.api.overview import _goal_summaries
        result = await _goal_summaries(new_user_uid, [])
        assert result == []

    async def test_nudges_suggest_basics(self, new_user_uid):
        from finagent.api.overview import _nudges
        nudges = await _nudges(new_user_uid, None, [], [], {"total": 0})
        titles = [n["title"] for n in nudges]
        assert any("goal" in t.lower() for t in titles), \
            "Should nudge new user to create goals"

    async def test_data_gaps_show_all(self, new_user_uid):
        from finagent.api.overview import _data_gaps
        gaps = await _data_gaps(new_user_uid)
        labels = {g["label"] for g in gaps}
        assert "Real Estate" in labels
        assert "Gold & SGBs" in labels


@pytest.fixture
async def salaried_user():
    uid = await store.get_or_create_user("salaried", "sal@test.com", "Rahul")
    # Clean up before creating
    await store.clear_goals(uid)
    # Profile
    p = UserProfile(user_id=uid, name="Rahul", age=28,
                    monthly_income=120000, total_monthly_expenses=50000,
                    monthly_sip=20000, emis=0, risk_tolerance="Moderate")
    await store.save_profile(p)
    # EPF
    await store.save_assets(uid, "epf_ppf",
                           [{"epf_balance": 400000, "ppf_balance": 200000,
                             "epf_contribution": 10000}])
    # FD
    await store.save_assets(uid, "fd",
                           [{"bank": "SBI", "amount": 300000, "rate": 7.1}])
    # MF holdings
    holdings = [
        MFHolding(scheme_name="PPFAS Flexi Cap", folio="F1", amc="PPFAS",
                  units=500, nav=50, current_value=250000, invested_value=200000),
        MFHolding(scheme_name="Nifty 50 Index", folio="F2", amc="UTI",
                  units=100, nav=200, current_value=200000, invested_value=180000),
    ]
    # Goal
    target_date = (date.today() + timedelta(days=365 * 5)).isoformat()
    await store.save_goal(Goal(user_id=uid, name="House Down Payment",
                               template="custom", target_amount=2000000,
                               target_date=target_date))
    return uid, holdings


@pytest.mark.asyncio
class TestOverviewSalariedProfessional:
    """Typical 28yo salaried professional: income, MFs, EPF, one goal."""

    async def test_net_worth_includes_all_assets(self, salaried_user):
        uid, holdings = salaried_user
        from finagent.api.overview import _net_worth
        nw = await _net_worth(uid, holdings)
        # EPF(4L) + PPF(2L) + FD(3L) + MF(4.5L) = 13.5L
        assert abs(nw["total"] - 1350000) < 100
        assert nw["total_liabilities"] == 0

    async def test_mf_values_correct(self, salaried_user):
        uid, holdings = salaried_user
        from finagent.api.overview import _net_worth
        nw = await _net_worth(uid, holdings)
        assert nw["mf_value"] == 450000
        assert nw["mf_invested"] == 380000
        assert nw["mf_gain"] == 70000

    async def test_allocation_buckets(self, salaried_user):
        uid, holdings = salaried_user
        from finagent.api.overview import _net_worth
        nw = await _net_worth(uid, holdings)
        alloc = nw["allocation"]
        # MF(4.5L) → Equity, EPF+PPF(6L)+FD(3L) → Debt
        assert alloc.get("Equity", 0) == 450000
        assert abs(alloc.get("Debt", 0) - 900000) < 100

    async def test_cash_flow_computed(self, salaried_user):
        uid, _ = salaried_user
        from finagent.api.overview import _cash_flow
        profile = await store.load_profile(uid)
        cf = _cash_flow(profile)
        assert cf is not None
        assert cf["income"] == 120000
        assert cf["expenses"] == 50000
        assert cf["investments"] == 20000
        # surplus = 120k - 50k - 0 emi - 20k sip = 50k
        assert cf["surplus"] == 50000

    async def test_savings_rate(self, salaried_user):
        uid, _ = salaried_user
        from finagent.api.overview import _cash_flow
        profile = await store.load_profile(uid)
        cf = _cash_flow(profile)
        # savings_rate = (120k - 50k - 0) / 120k * 100 = 58%
        assert cf["savings_rate"] == 58

    async def test_has_one_goal(self, salaried_user):
        uid, holdings = salaried_user
        from finagent.api.overview import _goal_summaries
        goals = await _goal_summaries(uid, holdings)
        assert len(goals) == 1
        assert goals[0]["name"] == "House Down Payment"
        assert goals[0]["target_amount"] == 2000000

    async def test_ideal_allocation_for_age(self, salaried_user):
        uid, _ = salaried_user
        from finagent.api.overview import _ideal_allocation
        profile = await store.load_profile(uid)
        ideal = _ideal_allocation(profile)
        # Age 28, Moderate → equity = 100-28 = 72
        assert ideal["Equity"] == 72
        assert ideal["Gold"] == 10


@pytest.fixture
async def hnw_user():
    uid = await store.get_or_create_user("hnw", "hnw@test.com", "Priya")
    p = UserProfile(user_id=uid, name="Priya", age=35,
                    monthly_income=300000, total_monthly_expenses=100000,
                    monthly_sip=50000, emis=45000, risk_tolerance="Aggressive")
    await store.save_profile(p)
    # Assets
    await store.save_assets(uid, "epf_ppf",
                           [{"epf_balance": 1500000, "ppf_balance": 800000}])
    await store.save_assets(uid, "fd",
                           [{"bank": "HDFC", "amount": 1000000, "rate": 7.5}])
    await store.save_assets(uid, "gold",
                           [{"type": "sgb", "value": 500000},
                            {"type": "physical", "value": 300000}])
    await store.save_assets(uid, "realestate",
                           [{"type": "self_occupied", "current_value": 8000000,
                             "purchase_price": 5000000}])
    await store.save_assets(uid, "esop",
                           [{"company": "Amazon", "vested": 2000000}])
    await store.save_assets(uid, "loan",
                           [{"loan_type": "Home Loan", "outstanding": 3000000,
                             "emi": 45000}])
    holdings = [
        MFHolding(scheme_name="Axis Small Cap", folio="F1", amc="Axis",
                  units=1000, nav=80, current_value=800000, invested_value=600000),
    ]
    return uid, holdings


@pytest.mark.asyncio
class TestOverviewHighNetWorth:
    """35yo with multiple asset classes including real estate and loans."""

    async def test_net_worth_assets_minus_liabilities(self, hnw_user):
        uid, holdings = hnw_user
        from finagent.api.overview import _net_worth
        nw = await _net_worth(uid, holdings)
        # Assets: EPF(15L)+PPF(8L)+FD(10L)+Gold(8L)+RE(80L)+ESOP(20L)+MF(8L) = 149L
        # Liabilities: Loan(30L)
        expected_assets = 1500000 + 800000 + 1000000 + 800000 + 8000000 + 2000000 + 800000
        expected_liabilities = 3000000
        assert abs(nw["total_assets"] - expected_assets) < 100
        assert abs(nw["total_liabilities"] - expected_liabilities) < 100
        assert abs(nw["total"] - (expected_assets - expected_liabilities)) < 100

    async def test_all_allocation_buckets_present(self, hnw_user):
        uid, holdings = hnw_user
        from finagent.api.overview import _net_worth
        nw = await _net_worth(uid, holdings)
        alloc = nw["allocation"]
        assert alloc.get("Equity", 0) > 0
        assert alloc.get("Debt", 0) > 0
        assert alloc.get("Gold", 0) > 0
        assert alloc.get("Real Estate", 0) > 0

    async def test_gold_value_sums_all_types(self, hnw_user):
        uid, holdings = hnw_user
        from finagent.api.overview import _net_worth
        nw = await _net_worth(uid, holdings)
        assert nw["allocation"]["Gold"] == 800000  # 5L SGB + 3L physical

    async def test_liabilities_in_response(self, hnw_user):
        uid, holdings = hnw_user
        from finagent.api.overview import _net_worth
        nw = await _net_worth(uid, holdings)
        assert "Home Loan" in nw["liabilities"]
        assert nw["liabilities"]["Home Loan"] == 3000000

    async def test_emi_ratio(self, hnw_user):
        uid, _ = hnw_user
        from finagent.api.overview import _cash_flow
        profile = await store.load_profile(uid)
        cf = _cash_flow(profile)
        # emi_ratio = 45000/300000 * 100 = 15%
        assert cf["emi_ratio"] == 15

    async def test_aggressive_allocation_shift(self, hnw_user):
        uid, _ = hnw_user
        from finagent.api.overview import _ideal_allocation
        profile = await store.load_profile(uid)
        ideal = _ideal_allocation(profile)
        # Age 35, Aggressive → equity = (100-35)+10 = 75
        assert ideal["Equity"] == 75


@pytest.fixture
async def edge_uid():
    import uuid
    uid = await store.get_or_create_user(f"edge-{uuid.uuid4().hex[:8]}", "edge@test.com", "Edge")
    return uid


@pytest.mark.asyncio
class TestOverviewEdgeCases:
    """Edge cases that could break the overview."""

    async def test_zero_income_no_division_error(self, edge_uid):
        """savings_rate and emi_ratio must not divide by zero."""
        from finagent.api.overview import _cash_flow
        p = UserProfile(user_id=edge_uid, monthly_income=0)
        cf = _cash_flow(p)
        # monthly_income=0 → should return None (no cash flow to show)
        assert cf is None

    async def test_none_values_in_assets(self, edge_uid):
        """Assets with None values should not crash net worth."""
        from finagent.api.overview import _net_worth
        await store.save_assets(edge_uid, "fd",
                               [{"bank": "SBI", "amount": None}])
        nw = await _net_worth(edge_uid, [])
        assert isinstance(nw["total"], (int, float))

    async def test_negative_loan_doesnt_add_to_assets(self, edge_uid):
        """Loans should only appear in liabilities, never assets."""
        from finagent.api.overview import _net_worth
        await store.save_assets(edge_uid, "loan",
                               [{"loan_type": "Home", "outstanding": 5000000}])
        nw = await _net_worth(edge_uid, [])
        assert nw["total_assets"] == 0
        assert nw["total_liabilities"] == 5000000
        assert nw["total"] == -5000000

    async def test_mf_not_double_counted(self, edge_uid):
        """MF from holdings param should not also be counted from user_assets."""
        from finagent.api.overview import _net_worth
        # Save MF in user_assets (declared)
        await store.save_assets(edge_uid, "mf",
                               [{"scheme": "Test Fund", "current_value": 100000,
                                 "source": "declared"}])
        # Also pass as holdings (verified)
        holdings = [MFHolding(scheme_name="Test Fund", folio="F1", amc="Test",
                              units=100, nav=1000, current_value=100000)]
        nw = await _net_worth(edge_uid, holdings)
        # MF should be counted once (from holdings), not twice
        assert nw["mf_value"] == 100000
        assert abs(nw["assets"].get("Mutual Funds", 0) - 100000) < 1

    async def test_projections_with_zero_surplus(self, edge_uid):
        """Cash flow projections should handle zero surplus gracefully."""
        from finagent.api.overview import _cash_flow
        p = UserProfile(user_id=edge_uid, monthly_income=100000,
                        total_monthly_expenses=60000, emis=20000, monthly_sip=20000)
        cf = _cash_flow(p)
        assert cf["surplus"] == 0
        # Projections should all be 0
        for scenario in cf["projections"]:
            for yr_val in scenario["values"].values():
                assert yr_val == 0

    async def test_data_gaps_exclude_existing(self, edge_uid):
        """Data gaps should not show asset types user already has."""
        from finagent.api.overview import _data_gaps
        await store.save_assets(edge_uid, "gold", [{"type": "sgb", "value": 100}])
        await store.save_assets(edge_uid, "realestate", [{"type": "plot", "current_value": 100}])
        gaps = await _data_gaps(edge_uid)
        labels = {g["label"] for g in gaps}
        assert "Gold & SGBs" not in labels
        assert "Real Estate" not in labels
        assert "Loans & EMIs" in labels  # still missing
