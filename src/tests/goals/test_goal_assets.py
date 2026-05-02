"""Tests for goal-to-asset linking."""
import pytest
import uuid

from finagent.api.goals import _asset_value, _compute_goal_progress
from finagent.models.goal import Goal
from finagent.storage import save_assets, get_or_create_user, load_assets


@pytest.fixture
async def goal_uid():
    return await get_or_create_user("test-goal-assets", "goal@test.com", "Test Goal")


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


@pytest.mark.asyncio
class TestGoalProgressWithAssets:
    async def test_asset_linked_to_goal(self, goal_uid):
        await save_assets(goal_uid, "fd", [{"bank": "SBI", "amount": 300000}])
        items = await load_assets(goal_uid, "fd")
        fd_id = items[0].get("id", 0)

        goal = Goal(user_id=goal_uid, name="Emergency Fund", template="emergency",
                    target_amount=500000, target_date="2027-01-01",
                    linked_folios=[{"asset_type": "fd", "asset_id": fd_id, "pct": 100}])
        result = await _compute_goal_progress(goal, [], goal_uid)
        assert result["current_value"] == 300000
        assert result["progress_pct"] == 60.0

    async def test_partial_allocation(self, goal_uid):
        await save_assets(goal_uid, "gold", [{"type": "SGB", "value": 400000}])
        items = await load_assets(goal_uid, "gold")
        gold_id = items[0].get("id", 0)

        goal = Goal(user_id=goal_uid, name="Travel", template="travel",
                    target_amount=200000, target_date="2027-06-01",
                    linked_folios=[{"asset_type": "gold", "asset_id": gold_id, "pct": 50}])
        result = await _compute_goal_progress(goal, [], goal_uid)
        assert result["current_value"] == 200000  # 50% of 400000
        assert result["progress_pct"] == 100.0

    async def test_mixed_mf_and_asset(self, goal_uid):
        """Goal with both MF holdings and assets linked."""
        await save_assets(goal_uid, "nps", [{"nps_balance": 100000}])
        goal = Goal(user_id=goal_uid, name="Retirement", template="retirement",
                    target_amount=1000000, target_date="2050-01-01",
                    linked_folios=[{"asset_type": "nps", "asset_id": 0, "pct": 100}])
        result = await _compute_goal_progress(goal, [], goal_uid)
        assert result["current_value"] == 100000
        assert result["progress_pct"] == 10.0


@pytest.mark.asyncio
class TestLinkAssetToGoalAction:
    async def test_link_fd_to_goal(self):
        link_uid = await get_or_create_user(f"test-link-{uuid.uuid4().hex[:8]}", "l@t.com", "T")
        await save_assets(link_uid, "fd", [{"bank": "SBI", "amount": 300000}])
        from finagent.storage import save_goal, load_goals
        goal = Goal(user_id=link_uid, name="Emergency Fund", template="emergency",
                    target_amount=500000, target_date="2027-01-01")
        gid = await save_goal(goal)

        from finagent.actions.link_asset_to_goal import execute
        result = await execute({"goal_name": "emergency", "asset_type": "fd", "match": "SBI"}, link_uid, {})
        assert "linked" in result["message"].lower() or "already" in result["message"].lower()

        goals = await load_goals(link_uid)
        updated = next(g for g in goals if g.id == gid)
        assert any(lf.get("asset_type") == "fd" for lf in updated.linked_folios)

    async def test_duplicate_link_rejected(self):
        dup_uid = await get_or_create_user(f"test-dup-{uuid.uuid4().hex[:8]}", "d@t.com", "T")
        await save_assets(dup_uid, "nps", [{"nps_balance": 100000}])
        from finagent.storage import save_goal, load_assets as la
        items = await la(dup_uid, "nps")
        aid = items[0].get("id", 0)
        goal = Goal(user_id=dup_uid, name="Retirement", template="retirement",
                    target_amount=10000000, target_date="2050-01-01",
                    linked_folios=[{"asset_type": "nps", "asset_id": aid, "pct": 100}])
        await save_goal(goal)

        from finagent.actions.link_asset_to_goal import execute
        result = await execute({"goal_name": "retirement", "asset_type": "nps"}, dup_uid, {})
        assert "already linked" in result["message"]

    async def test_link_mf_from_holdings(self):
        """Link a CAS-uploaded MF holding to a goal via folio key."""
        from finagent.models.mf import MFHolding
        from finagent.storage import save_goal, reconcile_and_save, load_goals
        mf_uid = await get_or_create_user(f"test-mf-{uuid.uuid4().hex[:8]}", "mf@t.com", "T")
        h = MFHolding(scheme_name="Parag Parikh Flexi Cap Fund Direct Growth",
                      folio="12345", amc="PPFAS", current_value=200000)
        await reconcile_and_save(mf_uid, "mf", [h], source_detail="cas_upload")
        goal = Goal(user_id=mf_uid, name="House Purchase", template="house",
                    target_amount=5000000, target_date="2030-01-01")
        gid = await save_goal(goal)

        from finagent.actions.link_asset_to_goal import execute
        result = await execute({"goal_name": "house", "asset_type": "mf", "match": "parag parikh"}, mf_uid, {})
        assert "Parag Parikh" in result["message"] or "linked" in result["message"].lower()

        goals = await load_goals(mf_uid)
        updated = next(g for g in goals if g.id == gid)
        assert any(lf.get("folio", "").startswith("12345/") for lf in updated.linked_folios)

    async def test_link_mf_from_declared(self):
        """Link a chat-declared MF to a goal via unified load_mf_assets."""
        from finagent.storage import save_goal, load_goals
        mfd_uid = await get_or_create_user(f"test-mfd-{uuid.uuid4().hex[:8]}", "mfd@t.com", "T")
        await save_assets(mfd_uid, "mf", [{"scheme": "HDFC Conservative Hybrid", "current_value": 150000}], source="declared")
        goal = Goal(user_id=mfd_uid, name="Marriage Fund", template="marriage",
                    target_amount=1500000, target_date="2028-01-01")
        gid = await save_goal(goal)

        from finagent.actions.link_asset_to_goal import execute
        result = await execute({"goal_name": "marriage", "asset_type": "mf", "match": "hdfc conservative"}, mfd_uid, {})
        assert "linked" in result["message"].lower() or "HDFC" in result["message"]

        goals = await load_goals(mfd_uid)
        updated = next(g for g in goals if g.id == gid)
        assert any("HDFC Conservative Hybrid" in str(lf) for lf in updated.linked_folios)

    async def test_mf_sip_included_in_goal_progress(self):
        """Declared MF monthly_sip should count in goal's monthly_sip total."""
        from finagent.storage import save_goal
        from finagent.api.goals import _compute_goal_progress
        sip_uid = await get_or_create_user(f"test-sip-{uuid.uuid4().hex[:8]}", "sip@t.com", "T")
        await save_assets(sip_uid, "mf", [{"scheme": "Nifty 50", "current_value": 100000, "monthly_sip": 5000}], source="declared")
        items = await load_assets(sip_uid, "mf")
        aid = items[0]["id"]
        goal = Goal(user_id=sip_uid, name="Wealth", template="custom",
                    target_amount=1000000, target_date="2030-01-01",
                    linked_folios=[{"asset_type": "mf", "asset_id": aid, "pct": 100}])
        await save_goal(goal)
        progress = await _compute_goal_progress(goal, [], sip_uid)
        assert progress["monthly_sip"] == 5000
        assert progress["current_value"] == 100000

    async def test_link_mf_no_holdings(self):
        """MF link fails gracefully when no holdings exist."""
        from finagent.storage import save_goal
        mfn_uid = await get_or_create_user(f"test-mfn-{uuid.uuid4().hex[:8]}", "mfn@t.com", "T")
        goal = Goal(user_id=mfn_uid, name="Travel", template="travel",
                    target_amount=200000, target_date="2027-01-01")
        await save_goal(goal)

        from finagent.actions.link_asset_to_goal import execute
        result = await execute({"goal_name": "travel", "asset_type": "mf", "match": "SBI Bluechip"}, mfn_uid, {})
        assert "error" in result


@pytest.mark.asyncio
class TestSuggestedEmergencyFund:
    async def test_auto_creates_when_expenses_available(self):
        from finagent.storage import load_goals
        from finagent.orchestrator.engine import _maybe_suggest_emergency_fund
        from finagent.models.profile import UserProfile
        ef_uid = await get_or_create_user(f"test-ef-{uuid.uuid4().hex[:8]}", "ef@t.com", "T")
        profile = UserProfile(user_id=ef_uid, total_monthly_expenses=60000)
        await _maybe_suggest_emergency_fund(ef_uid, profile)
        goals = await load_goals(ef_uid)
        ef = next((g for g in goals if g.template == "emergency"), None)
        assert ef is not None
        assert ef.status == "suggested"
        assert ef.target_amount == 360000  # 6 x 60000

    async def test_no_duplicate_if_exists(self):
        from finagent.storage import save_goal, load_goals
        from finagent.orchestrator.engine import _maybe_suggest_emergency_fund
        from finagent.models.profile import UserProfile
        efd_uid = await get_or_create_user(f"test-efd-{uuid.uuid4().hex[:8]}", "efd@t.com", "T")
        await save_goal(Goal(user_id=efd_uid, name="Emergency Fund", template="emergency",
                             target_amount=300000, target_date="2027-01-01"))
        profile = UserProfile(user_id=efd_uid, total_monthly_expenses=60000)
        await _maybe_suggest_emergency_fund(efd_uid, profile)
        ef_goals = [g for g in await load_goals(efd_uid) if g.template == "emergency"]
        assert len(ef_goals) == 1

    async def test_goal_status_active_by_default(self):
        from finagent.storage import save_goal, load_goals
        sta_uid = await get_or_create_user(f"test-sta-{uuid.uuid4().hex[:8]}", "sta@t.com", "T")
        goal = Goal(user_id=sta_uid, name="House", template="house",
                    target_amount=5000000, target_date="2030-01-01")
        gid = await save_goal(goal)
        goals = await load_goals(sta_uid)
        loaded = next(g for g in goals if g.id == gid)
        assert loaded.status == "active"

    async def test_accept_changes_status(self):
        from finagent.storage import save_goal, load_goals
        acc_uid = await get_or_create_user(f"test-acc-{uuid.uuid4().hex[:8]}", "acc@t.com", "T")
        goal = Goal(user_id=acc_uid, name="Emergency Fund", template="emergency",
                    target_amount=360000, target_date="", status="suggested")
        gid = await save_goal(goal)
        goals = await load_goals(acc_uid)
        loaded = next(g for g in goals if g.id == gid)
        loaded.status = "active"
        await save_goal(loaded)
        goals2 = await load_goals(acc_uid)
        reloaded = next(g for g in goals2 if g.id == gid)
        assert reloaded.status == "active"

    async def test_empty_target_date_progress(self):
        """Suggested emergency fund with no target_date doesn't crash."""
        etd_uid = await get_or_create_user(f"test-etd-{uuid.uuid4().hex[:8]}", "etd@t.com", "T")
        goal = Goal(user_id=etd_uid, name="Emergency Fund", template="emergency",
                    target_amount=360000, target_date="", status="suggested")
        result = await _compute_goal_progress(goal, [], etd_uid)
        assert result["current_value"] == 0
        assert result["progress_pct"] == 0
        assert result["on_track"] is False
