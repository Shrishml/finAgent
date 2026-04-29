"""Tests for goal-to-asset linking."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from finagent.api.goals import _asset_value, _compute_goal_progress
from finagent.models.goal import Goal
from finagent.storage.sqlite import save_assets, get_or_create_user, load_assets


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


class TestLinkAssetToGoalAction:
    def test_link_fd_to_goal(self):
        import asyncio, uuid
        uid = get_or_create_user(f"test-link-{uuid.uuid4().hex[:8]}", "l@t.com", "T")
        save_assets(uid, "fd", [{"bank": "SBI", "amount": 300000}])
        from finagent.storage.sqlite import save_goal, load_goals
        goal = Goal(user_id=uid, name="Emergency Fund", template="emergency",
                    target_amount=500000, target_date="2027-01-01")
        gid = save_goal(goal)

        from finagent.actions.link_asset_to_goal import execute
        result = asyncio.get_event_loop().run_until_complete(
            execute({"goal_name": "emergency", "asset_type": "fd", "match": "SBI"}, uid, {}))
        assert "✅" in result["message"]

        updated = next(g for g in load_goals(uid) if g.id == gid)
        assert any(lf.get("asset_type") == "fd" for lf in updated.linked_folios)

    def test_duplicate_link_rejected(self):
        import asyncio, uuid
        uid = get_or_create_user(f"test-dup-{uuid.uuid4().hex[:8]}", "d@t.com", "T")
        save_assets(uid, "nps", [{"nps_balance": 100000}])
        from finagent.storage.sqlite import save_goal, load_assets as la
        items = la(uid, "nps")
        aid = items[0].get("id", 0)
        goal = Goal(user_id=uid, name="Retirement", template="retirement",
                    target_amount=10000000, target_date="2050-01-01",
                    linked_folios=[{"asset_type": "nps", "asset_id": aid, "pct": 100}])
        save_goal(goal)

        from finagent.actions.link_asset_to_goal import execute
        result = asyncio.get_event_loop().run_until_complete(
            execute({"goal_name": "retirement", "asset_type": "nps"}, uid, {}))
        assert "already linked" in result["message"]

    def test_link_mf_from_holdings(self):
        """Link a CAS-uploaded MF holding to a goal via folio key."""
        import asyncio, uuid
        from finagent.models.mf import MFHolding
        from finagent.storage.sqlite import save_goal, reconcile_and_save, load_goals
        uid = get_or_create_user(f"test-mf-{uuid.uuid4().hex[:8]}", "mf@t.com", "T")
        h = MFHolding(scheme_name="Parag Parikh Flexi Cap Fund Direct Growth",
                      folio="12345", amc="PPFAS", current_value=200000)
        reconcile_and_save(uid, "mf", [h], source_detail="cas_upload")
        goal = Goal(user_id=uid, name="House Purchase", template="house",
                    target_amount=5000000, target_date="2030-01-01")
        gid = save_goal(goal)

        from finagent.actions.link_asset_to_goal import execute
        result = asyncio.get_event_loop().run_until_complete(
            execute({"goal_name": "house", "asset_type": "mf", "match": "parag parikh"}, uid, {}))
        assert "✅" in result["message"]
        assert "Parag Parikh" in result["message"]

        updated = next(g for g in load_goals(uid) if g.id == gid)
        assert any(lf.get("folio", "").startswith("12345/") for lf in updated.linked_folios)

    def test_link_mf_from_declared(self):
        """Link a chat-declared MF to a goal via unified load_mf_assets."""
        import asyncio, uuid
        from finagent.storage.sqlite import save_goal, load_goals
        uid = get_or_create_user(f"test-mfd-{uuid.uuid4().hex[:8]}", "mfd@t.com", "T")
        save_assets(uid, "mf", [{"scheme": "HDFC Conservative Hybrid", "current_value": 150000}], source="declared")
        goal = Goal(user_id=uid, name="Marriage Fund", template="marriage",
                    target_amount=1500000, target_date="2028-01-01")
        gid = save_goal(goal)

        from finagent.actions.link_asset_to_goal import execute
        result = asyncio.get_event_loop().run_until_complete(
            execute({"goal_name": "marriage", "asset_type": "mf", "match": "hdfc conservative"}, uid, {}))
        assert "✅" in result["message"]

        updated = next(g for g in load_goals(uid) if g.id == gid)
        # Declared MFs link via scheme_name as folio key (no folio number)
        assert any("HDFC Conservative Hybrid" in str(lf) for lf in updated.linked_folios)

    def test_mf_sip_included_in_goal_progress(self):
        """Declared MF monthly_sip should count in goal's monthly_sip total."""
        import uuid
        from finagent.storage.sqlite import save_goal, load_goals
        from finagent.api.goals import _compute_goal_progress
        uid = get_or_create_user(f"test-sip-{uuid.uuid4().hex[:8]}", "sip@t.com", "T")
        save_assets(uid, "mf", [{"scheme": "Nifty 50", "current_value": 100000, "monthly_sip": 5000}], source="declared")
        items = load_assets(uid, "mf")
        aid = items[0]["id"]
        goal = Goal(user_id=uid, name="Wealth", template="custom",
                    target_amount=1000000, target_date="2030-01-01",
                    linked_folios=[{"asset_type": "mf", "asset_id": aid, "pct": 100}])
        save_goal(goal)
        progress = _compute_goal_progress(goal, [], uid)
        assert progress["monthly_sip"] == 5000
        assert progress["current_value"] == 100000

    def test_link_mf_no_holdings(self):
        """MF link fails gracefully when no holdings exist."""
        import asyncio, uuid
        from finagent.storage.sqlite import save_goal
        uid = get_or_create_user(f"test-mfn-{uuid.uuid4().hex[:8]}", "mfn@t.com", "T")
        goal = Goal(user_id=uid, name="Travel", template="travel",
                    target_amount=200000, target_date="2027-01-01")
        save_goal(goal)

        from finagent.actions.link_asset_to_goal import execute
        result = asyncio.get_event_loop().run_until_complete(
            execute({"goal_name": "travel", "asset_type": "mf", "match": "SBI Bluechip"}, uid, {}))
        assert "error" in result


class TestSuggestedEmergencyFund:
    def test_auto_creates_when_expenses_available(self):
        import uuid
        from finagent.storage.sqlite import load_goals
        from finagent.orchestrator.engine import _maybe_suggest_emergency_fund
        from finagent.models.profile import UserProfile
        uid = get_or_create_user(f"test-ef-{uuid.uuid4().hex[:8]}", "ef@t.com", "T")
        profile = UserProfile(user_id=uid, total_monthly_expenses=60000)
        _maybe_suggest_emergency_fund(uid, profile)
        goals = load_goals(uid)
        ef = next((g for g in goals if g.template == "emergency"), None)
        assert ef is not None
        assert ef.status == "suggested"
        assert ef.target_amount == 360000  # 6 × 60000

    def test_no_duplicate_if_exists(self):
        import uuid
        from finagent.storage.sqlite import save_goal, load_goals
        from finagent.orchestrator.engine import _maybe_suggest_emergency_fund
        from finagent.models.profile import UserProfile
        uid = get_or_create_user(f"test-efd-{uuid.uuid4().hex[:8]}", "efd@t.com", "T")
        save_goal(Goal(user_id=uid, name="Emergency Fund", template="emergency",
                       target_amount=300000, target_date="2027-01-01"))
        profile = UserProfile(user_id=uid, total_monthly_expenses=60000)
        _maybe_suggest_emergency_fund(uid, profile)
        ef_goals = [g for g in load_goals(uid) if g.template == "emergency"]
        assert len(ef_goals) == 1

    def test_goal_status_active_by_default(self):
        import uuid
        from finagent.storage.sqlite import save_goal, load_goals
        uid = get_or_create_user(f"test-sta-{uuid.uuid4().hex[:8]}", "sta@t.com", "T")
        goal = Goal(user_id=uid, name="House", template="house",
                    target_amount=5000000, target_date="2030-01-01")
        gid = save_goal(goal)
        loaded = next(g for g in load_goals(uid) if g.id == gid)
        assert loaded.status == "active"

    def test_accept_changes_status(self):
        import uuid
        from finagent.storage.sqlite import save_goal, load_goals
        uid = get_or_create_user(f"test-acc-{uuid.uuid4().hex[:8]}", "acc@t.com", "T")
        goal = Goal(user_id=uid, name="Emergency Fund", template="emergency",
                    target_amount=360000, target_date="", status="suggested")
        gid = save_goal(goal)
        loaded = next(g for g in load_goals(uid) if g.id == gid)
        loaded.status = "active"
        save_goal(loaded)
        reloaded = next(g for g in load_goals(uid) if g.id == gid)
        assert reloaded.status == "active"

    def test_empty_target_date_progress(self):
        """Suggested emergency fund with no target_date doesn't crash."""
        import uuid
        uid = get_or_create_user(f"test-etd-{uuid.uuid4().hex[:8]}", "etd@t.com", "T")
        goal = Goal(user_id=uid, name="Emergency Fund", template="emergency",
                    target_amount=360000, target_date="", status="suggested")
        result = _compute_goal_progress(goal, [], uid)
        assert result["current_value"] == 0
        assert result["progress_pct"] == 0
        assert result["on_track"] is False
