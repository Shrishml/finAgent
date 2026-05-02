"""Unit tests for goal model and storage."""
import pytest
from datetime import date, timedelta
from finagent.models.goal import Goal, GOAL_TEMPLATES
import finagent.storage as db


@pytest.fixture
async def user_id():
    uid = await db.get_or_create_user("test-google-id", "test@test.com", "Test User")
    await db.clear_goals(uid)  # Clean up before each test
    return uid


class TestGoalModel:
    def test_template_default_growth(self):
        g = Goal(user_id=1, name="Retire", template="retirement", target_amount=5_000_000, target_date="2035-01-01")
        assert g.growth_rate == 0.12

    def test_custom_growth_override(self):
        g = Goal(user_id=1, name="House", template="house", target_amount=1_000_000, target_date="2030-01-01", growth_rate=0.15)
        assert g.growth_rate == 0.15

    def test_all_templates_have_defaults(self):
        assert len(GOAL_TEMPLATES) == 8
        for key, tmpl in GOAL_TEMPLATES.items():
            assert "label" in tmpl
            assert 0 < tmpl["default_growth"] <= 0.20
            assert "suggested_amount" in tmpl


@pytest.mark.asyncio
class TestGoalStorage:
    async def test_create_and_load(self, user_id):
        g = Goal(user_id=user_id, name="Retirement", template="retirement", target_amount=5_000_000, target_date="2035-01-01", linked_folios=["F1/Scheme A"])
        gid = await db.save_goal(g)
        assert gid > 0

        goals = await db.load_goals(user_id)
        assert len(goals) == 1
        assert goals[0].name == "Retirement"
        assert goals[0].linked_folios == ["F1/Scheme A"]
        assert goals[0].growth_rate == 0.12

    async def test_update(self, user_id):
        g = Goal(user_id=user_id, name="House", template="house", target_amount=1_000_000, target_date="2030-01-01")
        gid = await db.save_goal(g)

        g.id = gid
        g.target_amount = 2_000_000
        await db.save_goal(g)

        goals = await db.load_goals(user_id)
        assert len(goals) == 1
        assert goals[0].target_amount == 2_000_000

    async def test_delete(self, user_id):
        gid = await db.save_goal(Goal(user_id=user_id, name="Trip", template="travel", target_amount=100_000, target_date="2027-01-01"))
        assert await db.delete_goal(gid, user_id) is True
        assert await db.load_goals(user_id) == []

    async def test_delete_wrong_user(self, user_id):
        gid = await db.save_goal(Goal(user_id=user_id, name="Trip", template="travel", target_amount=100_000, target_date="2027-01-01"))
        assert await db.delete_goal(gid, user_id + 999) is False
        assert len(await db.load_goals(user_id)) == 1

    async def test_clear_goals(self, user_id):
        await db.save_goal(Goal(user_id=user_id, name="A", template="custom", target_amount=1, target_date="2030-01-01"))
        await db.save_goal(Goal(user_id=user_id, name="B", template="custom", target_amount=2, target_date="2030-01-01"))
        await db.clear_goals(user_id)
        assert await db.load_goals(user_id) == []

    async def test_multiple_goals(self, user_id):
        await db.save_goal(Goal(user_id=user_id, name="Retire", template="retirement", target_amount=5_000_000, target_date="2035-01-01"))
        await db.save_goal(Goal(user_id=user_id, name="House", template="house", target_amount=1_000_000, target_date="2030-01-01"))
        await db.save_goal(Goal(user_id=user_id, name="Emergency", template="emergency", target_amount=300_000, target_date="2026-06-01"))
        assert len(await db.load_goals(user_id)) == 3

    async def test_isolation_between_users(self, user_id):
        user2 = await db.get_or_create_user("other-google-id", "other@test.com", "Other")
        await db.clear_goals(user2)  # Clean user2's goals too
        await db.save_goal(Goal(user_id=user_id, name="Mine", template="custom", target_amount=1, target_date="2030-01-01"))
        await db.save_goal(Goal(user_id=user2, name="Theirs", template="custom", target_amount=2, target_date="2030-01-01"))
        assert len(await db.load_goals(user_id)) == 1
        assert len(await db.load_goals(user2)) == 1
        assert (await db.load_goals(user_id))[0].name == "Mine"
