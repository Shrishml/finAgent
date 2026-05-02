"""Tests for UserProfile and Conversation storage (P1 + P2)."""
import pytest

from finagent.models.profile import UserProfile
from finagent.storage import (
    save_profile, load_profile, update_profile,
    save_message, load_conversation, clear_conversation,
    get_or_create_user,
)


async def _test_user() -> int:
    return await get_or_create_user("test-profile-user", "test@test.com", "Test User")


@pytest.mark.asyncio
class TestUserProfile:
    async def test_create_and_load(self):
        uid = await _test_user()
        p = UserProfile(user_id=uid, monthly_income=110000, occupation="engineer")
        await save_profile(p)
        loaded = await load_profile(uid)
        assert loaded is not None
        assert loaded.monthly_income == 110000
        assert loaded.occupation == "engineer"

    async def test_update_partial(self):
        uid = await _test_user()
        await save_profile(UserProfile(user_id=uid, monthly_income=100000))
        updated = await update_profile(uid, {"occupation": "manager"})
        assert updated.monthly_income == 100000  # preserved
        assert updated.occupation == "manager"  # updated

    async def test_onboarding_complete(self):
        uid = await _test_user()
        p = UserProfile(user_id=uid, onboarding_complete=True)
        await save_profile(p)
        loaded = await load_profile(uid)
        assert loaded.onboarding_complete is True

    def test_savings_rate(self):
        p = UserProfile(user_id=1, monthly_income=100000, monthly_expenses=60000)
        assert p.savings_rate == 0.4

    def test_savings_rate_no_income(self):
        p = UserProfile(user_id=1)
        assert p.savings_rate is None

    def test_loans_and_emi(self):
        p = UserProfile(user_id=1, loans=[
            {"type": "home", "emi": 35000},
            {"type": "car", "emi": 12000},
        ])
        assert len(p.loans) == 2
        assert p.total_emi == 47000

    async def test_load_nonexistent(self):
        assert await load_profile(999999) is None

    async def test_update_creates_if_missing(self):
        uid = await get_or_create_user("test-update-create", "u@t.com", "U")
        profile = await update_profile(uid, {"monthly_income": 50000})
        assert profile.monthly_income == 50000


@pytest.mark.asyncio
class TestConversation:
    async def test_save_and_load(self):
        uid = await _test_user()
        await clear_conversation(uid)
        await save_message(uid, "user", "I earn 1.1 lakh per month")
        await save_message(uid, "assistant", "Got it! Any bonuses?", {"pillar": "income"})
        msgs = await load_conversation(uid)
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[1]["metadata"]["pillar"] == "income"

    async def test_ordering(self):
        uid = await _test_user()
        await clear_conversation(uid)
        await save_message(uid, "user", "first")
        await save_message(uid, "assistant", "second")
        await save_message(uid, "user", "third")
        msgs = await load_conversation(uid)
        assert [m["content"] for m in msgs] == ["first", "second", "third"]

    async def test_limit(self):
        uid = await _test_user()
        await clear_conversation(uid)
        for i in range(10):
            await save_message(uid, "user", f"msg {i}")
        msgs = await load_conversation(uid, limit=3)
        assert len(msgs) == 3
        assert msgs[-1]["content"] == "msg 9"  # most recent

    async def test_auto_prune(self):
        uid = await get_or_create_user("test-prune-user", "p@t.com", "P")
        await clear_conversation(uid)
        for i in range(60):
            await save_message(uid, "user", f"msg {i}")
        msgs = await load_conversation(uid, limit=100)
        assert len(msgs) == 50  # pruned to max

    async def test_clear(self):
        uid = await _test_user()
        await save_message(uid, "user", "hello")
        await clear_conversation(uid)
        assert await load_conversation(uid) == []
