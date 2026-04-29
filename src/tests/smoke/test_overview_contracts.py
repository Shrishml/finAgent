"""Overview page contract tests: verify net worth, goals, cash flow, nudges
for different user personas.

Each persona represents a real user archetype. Tests verify the overview
API computes correct numbers — not just "doesn't crash" but "shows right data".
"""
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from finagent.models.profile import UserProfile
from finagent.models.goal import Goal
from finagent.models.mf import MFHolding


def _setup_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    import finagent.storage.sqlite as store
    store._DB_PATH = Path(path)
    store._DB_DIR = Path(path).parent
    return path, store


class TestOverviewNewUser(unittest.TestCase):
    """Brand new user — no data at all. Overview should not crash."""

    def setUp(self):
        self.db_path, self.store = _setup_db()
        self.uid = self.store.get_or_create_user("new-user", "new@test.com", "New")

    def tearDown(self):
        os.unlink(self.db_path)

    def test_net_worth_is_zero(self):
        from finagent.api.overview import _net_worth
        nw = _net_worth(self.uid, [])
        self.assertEqual(nw["total"], 0)
        self.assertEqual(nw["total_assets"], 0)
        self.assertEqual(nw["total_liabilities"], 0)

    def test_cash_flow_is_none_without_profile(self):
        from finagent.api.overview import _cash_flow
        self.assertIsNone(_cash_flow(None))

    def test_goal_summaries_empty(self):
        from finagent.api.overview import _goal_summaries
        self.assertEqual(_goal_summaries(self.uid, []), [])

    def test_nudges_suggest_basics(self):
        from finagent.api.overview import _nudges
        nudges = _nudges(self.uid, None, [], [], {"total": 0})
        titles = [n["title"] for n in nudges]
        self.assertTrue(any("goal" in t.lower() for t in titles),
                        "Should nudge new user to create goals")

    def test_data_gaps_show_all(self):
        from finagent.api.overview import _data_gaps
        gaps = _data_gaps(self.uid)
        labels = {g["label"] for g in gaps}
        self.assertIn("Real Estate", labels)
        self.assertIn("Gold & SGBs", labels)


class TestOverviewSalariedProfessional(unittest.TestCase):
    """Typical 28yo salaried professional: income, MFs, EPF, one goal."""

    def setUp(self):
        self.db_path, self.store = _setup_db()
        self.uid = self.store.get_or_create_user("salaried", "sal@test.com", "Rahul")
        # Profile
        p = UserProfile(user_id=self.uid, name="Rahul", age=28,
                        monthly_income=120000, total_monthly_expenses=50000,
                        monthly_sip=20000, emis=0, risk_tolerance="Moderate")
        self.store.save_profile(p)
        # EPF
        self.store.save_assets(self.uid, "epf_ppf",
                               [{"epf_balance": 400000, "ppf_balance": 200000,
                                 "epf_contribution": 10000}])
        # FD
        self.store.save_assets(self.uid, "fd",
                               [{"bank": "SBI", "amount": 300000, "rate": 7.1}])
        # MF holdings
        self.holdings = [
            MFHolding(scheme_name="PPFAS Flexi Cap", folio="F1", amc="PPFAS",
                      units=500, nav=50, current_value=250000, invested_value=200000),
            MFHolding(scheme_name="Nifty 50 Index", folio="F2", amc="UTI",
                      units=100, nav=200, current_value=200000, invested_value=180000),
        ]
        # Goal
        target_date = (date.today() + timedelta(days=365 * 5)).isoformat()
        self.store.save_goal(Goal(user_id=self.uid, name="House Down Payment",
                                  template="custom", target_amount=2000000,
                                  target_date=target_date))

    def tearDown(self):
        os.unlink(self.db_path)

    def test_net_worth_includes_all_assets(self):
        from finagent.api.overview import _net_worth
        nw = _net_worth(self.uid, self.holdings)
        # EPF(4L) + PPF(2L) + FD(3L) + MF(4.5L) = 13.5L
        self.assertAlmostEqual(nw["total"], 1350000, delta=100)
        self.assertEqual(nw["total_liabilities"], 0)

    def test_mf_values_correct(self):
        from finagent.api.overview import _net_worth
        nw = _net_worth(self.uid, self.holdings)
        self.assertEqual(nw["mf_value"], 450000)
        self.assertEqual(nw["mf_invested"], 380000)
        self.assertEqual(nw["mf_gain"], 70000)

    def test_allocation_buckets(self):
        from finagent.api.overview import _net_worth
        nw = _net_worth(self.uid, self.holdings)
        alloc = nw["allocation"]
        # MF(4.5L) → Equity, EPF+PPF(6L)+FD(3L) → Debt
        self.assertEqual(alloc.get("Equity", 0), 450000)
        self.assertAlmostEqual(alloc.get("Debt", 0), 900000, delta=100)

    def test_cash_flow_computed(self):
        from finagent.api.overview import _cash_flow
        profile = self.store.load_profile(self.uid)
        cf = _cash_flow(profile)
        self.assertIsNotNone(cf)
        self.assertEqual(cf["income"], 120000)
        self.assertEqual(cf["expenses"], 50000)
        self.assertEqual(cf["investments"], 20000)
        # surplus = 120k - 50k - 0 emi - 20k sip = 50k
        self.assertEqual(cf["surplus"], 50000)

    def test_savings_rate(self):
        from finagent.api.overview import _cash_flow
        profile = self.store.load_profile(self.uid)
        cf = _cash_flow(profile)
        # savings_rate = (120k - 50k - 0) / 120k * 100 = 58%
        self.assertEqual(cf["savings_rate"], 58)

    def test_has_one_goal(self):
        from finagent.api.overview import _goal_summaries
        goals = _goal_summaries(self.uid, self.holdings)
        self.assertEqual(len(goals), 1)
        self.assertEqual(goals[0]["name"], "House Down Payment")
        self.assertEqual(goals[0]["target_amount"], 2000000)

    def test_ideal_allocation_for_age(self):
        from finagent.api.overview import _ideal_allocation
        profile = self.store.load_profile(self.uid)
        ideal = _ideal_allocation(profile)
        # Age 28, Moderate → equity = 100-28 = 72
        self.assertEqual(ideal["Equity"], 72)
        self.assertEqual(ideal["Gold"], 10)


class TestOverviewHighNetWorth(unittest.TestCase):
    """35yo with multiple asset classes including real estate and loans."""

    def setUp(self):
        self.db_path, self.store = _setup_db()
        self.uid = self.store.get_or_create_user("hnw", "hnw@test.com", "Priya")
        p = UserProfile(user_id=self.uid, name="Priya", age=35,
                        monthly_income=300000, total_monthly_expenses=100000,
                        monthly_sip=50000, emis=45000, risk_tolerance="Aggressive")
        self.store.save_profile(p)
        # Assets
        self.store.save_assets(self.uid, "epf_ppf",
                               [{"epf_balance": 1500000, "ppf_balance": 800000}])
        self.store.save_assets(self.uid, "fd",
                               [{"bank": "HDFC", "amount": 1000000, "rate": 7.5}])
        self.store.save_assets(self.uid, "gold",
                               [{"type": "sgb", "value": 500000},
                                {"type": "physical", "value": 300000}])
        self.store.save_assets(self.uid, "realestate",
                               [{"type": "self_occupied", "current_value": 8000000,
                                 "purchase_price": 5000000}])
        self.store.save_assets(self.uid, "esop",
                               [{"company": "Amazon", "vested": 2000000}])
        self.store.save_assets(self.uid, "loan",
                               [{"loan_type": "Home Loan", "outstanding": 3000000,
                                 "emi": 45000}])
        self.holdings = [
            MFHolding(scheme_name="Axis Small Cap", folio="F1", amc="Axis",
                      units=1000, nav=80, current_value=800000, invested_value=600000),
        ]

    def tearDown(self):
        os.unlink(self.db_path)

    def test_net_worth_assets_minus_liabilities(self):
        from finagent.api.overview import _net_worth
        nw = _net_worth(self.uid, self.holdings)
        # Assets: EPF(15L)+PPF(8L)+FD(10L)+Gold(8L)+RE(80L)+ESOP(20L)+MF(8L) = 149L
        # Liabilities: Loan(30L)
        # Net = 119L
        expected_assets = 1500000 + 800000 + 1000000 + 800000 + 8000000 + 2000000 + 800000
        expected_liabilities = 3000000
        self.assertAlmostEqual(nw["total_assets"], expected_assets, delta=100)
        self.assertAlmostEqual(nw["total_liabilities"], expected_liabilities, delta=100)
        self.assertAlmostEqual(nw["total"], expected_assets - expected_liabilities, delta=100)

    def test_all_allocation_buckets_present(self):
        from finagent.api.overview import _net_worth
        nw = _net_worth(self.uid, self.holdings)
        alloc = nw["allocation"]
        # Should have Equity (MF+ESOP), Debt (EPF+PPF+FD), Gold, Real Estate
        self.assertGreater(alloc.get("Equity", 0), 0)
        self.assertGreater(alloc.get("Debt", 0), 0)
        self.assertGreater(alloc.get("Gold", 0), 0)
        self.assertGreater(alloc.get("Real Estate", 0), 0)

    def test_gold_value_sums_all_types(self):
        from finagent.api.overview import _net_worth
        nw = _net_worth(self.uid, self.holdings)
        self.assertEqual(nw["allocation"]["Gold"], 800000)  # 5L SGB + 3L physical

    def test_liabilities_in_response(self):
        from finagent.api.overview import _net_worth
        nw = _net_worth(self.uid, self.holdings)
        self.assertIn("Home Loan", nw["liabilities"])
        self.assertEqual(nw["liabilities"]["Home Loan"], 3000000)

    def test_emi_ratio(self):
        from finagent.api.overview import _cash_flow
        profile = self.store.load_profile(self.uid)
        cf = _cash_flow(profile)
        # emi_ratio = 45000/300000 * 100 = 15%
        self.assertEqual(cf["emi_ratio"], 15)

    def test_aggressive_allocation_shift(self):
        from finagent.api.overview import _ideal_allocation
        profile = self.store.load_profile(self.uid)
        ideal = _ideal_allocation(profile)
        # Age 35, Aggressive → equity = (100-35)+10 = 75
        self.assertEqual(ideal["Equity"], 75)


class TestOverviewEdgeCases(unittest.TestCase):
    """Edge cases that could break the overview."""

    def setUp(self):
        self.db_path, self.store = _setup_db()
        self.uid = self.store.get_or_create_user("edge", "edge@test.com", "Edge")

    def tearDown(self):
        os.unlink(self.db_path)

    def test_zero_income_no_division_error(self):
        """savings_rate and emi_ratio must not divide by zero."""
        from finagent.api.overview import _cash_flow
        p = UserProfile(user_id=self.uid, monthly_income=0)
        cf = _cash_flow(p)
        # monthly_income=0 → should return None (no cash flow to show)
        self.assertIsNone(cf)

    def test_none_values_in_assets(self):
        """Assets with None values should not crash net worth."""
        from finagent.api.overview import _net_worth
        self.store.save_assets(self.uid, "fd",
                               [{"bank": "SBI", "amount": None}])
        nw = _net_worth(self.uid, [])
        # Should not crash, amount=None → 0
        self.assertIsInstance(nw["total"], (int, float))

    def test_negative_loan_doesnt_add_to_assets(self):
        """Loans should only appear in liabilities, never assets."""
        from finagent.api.overview import _net_worth
        self.store.save_assets(self.uid, "loan",
                               [{"loan_type": "Home", "outstanding": 5000000}])
        nw = _net_worth(self.uid, [])
        self.assertEqual(nw["total_assets"], 0)
        self.assertEqual(nw["total_liabilities"], 5000000)
        self.assertEqual(nw["total"], -5000000)

    def test_mf_not_double_counted(self):
        """MF from holdings param should not also be counted from user_assets."""
        from finagent.api.overview import _net_worth
        # Save MF in user_assets (declared)
        self.store.save_assets(self.uid, "mf",
                               [{"scheme": "Test Fund", "current_value": 100000,
                                 "source": "declared"}])
        # Also pass as holdings (verified)
        holdings = [MFHolding(scheme_name="Test Fund", folio="F1", amc="Test",
                              units=100, nav=1000, current_value=100000)]
        nw = _net_worth(self.uid, holdings)
        # MF should be counted once (from holdings), not twice
        self.assertEqual(nw["mf_value"], 100000)
        self.assertAlmostEqual(nw["assets"].get("Mutual Funds", 0), 100000, delta=1)

    def test_projections_with_zero_surplus(self):
        """Cash flow projections should handle zero surplus gracefully."""
        from finagent.api.overview import _cash_flow
        p = UserProfile(user_id=self.uid, monthly_income=100000,
                        total_monthly_expenses=60000, emis=20000, monthly_sip=20000)
        cf = _cash_flow(p)
        self.assertEqual(cf["surplus"], 0)
        # Projections should all be 0
        for scenario in cf["projections"]:
            for yr_val in scenario["values"].values():
                self.assertEqual(yr_val, 0)

    def test_data_gaps_exclude_existing(self):
        """Data gaps should not show asset types user already has."""
        from finagent.api.overview import _data_gaps
        self.store.save_assets(self.uid, "gold", [{"type": "sgb", "value": 100}])
        self.store.save_assets(self.uid, "realestate", [{"type": "plot", "current_value": 100}])
        gaps = _data_gaps(self.uid)
        labels = {g["label"] for g in gaps}
        self.assertNotIn("Gold & SGBs", labels)
        self.assertNotIn("Real Estate", labels)
        self.assertIn("Loans & EMIs", labels)  # still missing


if __name__ == "__main__":
    unittest.main()
