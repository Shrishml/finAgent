"""Tests for goal-to-asset linking."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from finagent.api.goals import _asset_value, _compute_goal_progress
from finagent.models.goal import Goal
from finagent.storage.sqlite import save_assets, get_or_create_user


def _uid():
    return get_or_create_user("test-goal-assets", "goal@test.com", "Test Goal")


class TestAssetValue:
    def test_fd(self):
        assert _asset_value({"asset_type": "fd", "amount": 500000}) == 500000

    def test_gold(self):
        assert _asset_value({"asset_type": "gold", "value": 200000}) == 200000

    def test_epf_ppf_combined(self):
        assert _asset_value({"asset_type": "epf_ppf", "epf_balance": 100000, "ppf_balance": 300000}) == 400000

    def test_nps(self):
        assert _asset_value({"asset_type": "nps", "nps_balance": 200000}) == 200000

    def test_esop(self):
        assert _asset_value({"asset_type": "esop", "vested": 1000000}) == 1000000

    def test_realestate(self):
        assert _asset_value({"asset_type": "realestate", "current_value": 5000000}) == 5000000

    def test_missing_field(self):
        assert _asset_value({"asset_type": "fd"}) == 0

    def test_unknown_type(self):
        assert _asset_value({"asset_type": "unknown"}) == 0


class TestGoalProgressWithAssets:
    def test_asset_linked_to_goal(self):
        uid = _uid()
        save_assets(uid, "fd", [{"bank": "SBI", "amount": 300000}])
        items = __import__("finagent.storage.sqlite", fromlist=["load_assets"]).load_assets(uid, "fd")
        fd_id = items[0].get("id", 0)

        goal = Goal(user_id=uid, name="Emergency Fund", template="emergency",
                    target_amount=500000, target_date="2027-01-01",
                    linked_folios=[{"asset_type": "fd", "asset_id": fd_id, "pct": 100}])
        result = _compute_goal_progress(goal, [], uid)
        assert result["current_value"] == 300000
        assert result["progress_pct"] == 60.0

    def test_partial_allocation(self):
        uid = _uid()
        save_assets(uid, "gold", [{"type": "SGB", "value": 400000}])
        items = __import__("finagent.storage.sqlite", fromlist=["load_assets"]).load_assets(uid, "gold")
        gold_id = items[0].get("id", 0)

        goal = Goal(user_id=uid, name="Travel", template="travel",
                    target_amount=200000, target_date="2027-06-01",
                    linked_folios=[{"asset_type": "gold", "asset_id": gold_id, "pct": 50}])
        result = _compute_goal_progress(goal, [], uid)
        assert result["current_value"] == 200000  # 50% of 400000
        assert result["progress_pct"] == 100.0

    def test_mixed_mf_and_asset(self):
        """Goal with both MF holdings and assets linked."""
        uid = _uid()
        save_assets(uid, "nps", [{"nps_balance": 100000}])
        goal = Goal(user_id=uid, name="Retirement", template="retirement",
                    target_amount=1000000, target_date="2050-01-01",
                    linked_folios=[{"asset_type": "nps", "asset_id": 0, "pct": 100}])
        # No MF holdings, just NPS
        result = _compute_goal_progress(goal, [], uid)
        assert result["current_value"] == 100000
        assert result["progress_pct"] == 10.0
