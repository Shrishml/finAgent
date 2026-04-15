"""Tests for OnboardingAgent (P3)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from finagent.models.profile import UserProfile, PILLAR_ORDER
from finagent.agents.onboarding import (
    _apply_extractions, _completion_message, PILLAR_QUESTIONS, WELCOME_MSG,
)
from finagent.storage.sqlite import (
    save_profile, load_profile, get_or_create_user,
    save_message, load_conversation, clear_conversation,
)


def _test_user() -> int:
    return get_or_create_user("test-onboarding-user", "onboard@test.com", "Test Onboarder")


class TestApplyExtractions:
    def test_basic_income(self):
        p = UserProfile(user_id=1)
        _apply_extractions(p, {"monthly_income": 110000, "occupation": "engineer"})
        assert p.monthly_income == 110000
        assert p.occupation == "engineer"

    def test_string_number_conversion(self):
        p = UserProfile(user_id=1)
        _apply_extractions(p, {"monthly_income": "1,10,000"})
        assert p.monthly_income == 110000

    def test_loans_list(self):
        p = UserProfile(user_id=1)
        _apply_extractions(p, {"loans": [{"type": "home", "emi": 35000, "principal": 4000000}]})
        assert len(p.loans) == 1
        assert p.loans[0]["emi"] == 35000

    def test_ignores_unknown_fields(self):
        p = UserProfile(user_id=1)
        _apply_extractions(p, {"unknown_field": 42, "monthly_income": 50000})
        assert p.monthly_income == 50000
        assert not hasattr(p, "unknown_field") or getattr(p, "unknown_field", None) is None

    def test_none_values_skipped(self):
        p = UserProfile(user_id=1, monthly_income=100000)
        _apply_extractions(p, {"monthly_income": None})
        assert p.monthly_income == 100000  # unchanged

    def test_insurance_fields(self):
        p = UserProfile(user_id=1)
        _apply_extractions(p, {"term_cover": 10000000, "health_cover": 500000, "health_employer_only": True})
        assert p.term_cover == 10000000
        assert p.health_cover == 500000
        assert p.health_employer_only is True


class TestCompletionMessage:
    def test_full_profile(self):
        p = UserProfile(
            user_id=1, monthly_income=110000, monthly_expenses=62500,
            loans=[], pillars_completed=list(PILLAR_ORDER),
        )
        msg = _completion_message(p)
        assert "₹1,10,000" in msg
        assert "savings rate" in msg
        assert "debt free" in msg

    def test_with_skipped(self):
        p = UserProfile(
            user_id=1, monthly_income=100000,
            pillars_completed=["income", "expenses", "assets", "goals"],
            pillars_skipped=["liabilities", "insurance"],
        )
        msg = _completion_message(p)
        assert "Skipped" in msg
        assert "liabilities" in msg

    def test_no_insurance_warning(self):
        p = UserProfile(
            user_id=1, term_cover=0,
            pillars_completed=["insurance"],
        )
        msg = _completion_message(p)
        assert "needs attention" in msg


class TestPillarOrder:
    def test_strict_order(self):
        p = UserProfile(user_id=1)
        assert p.current_pillar == "income"
        p.pillars_completed.append("income")
        assert p.current_pillar == "expenses"
        p.pillars_completed.append("expenses")
        assert p.current_pillar == "assets"

    def test_skip_advances(self):
        p = UserProfile(user_id=1, pillars_completed=["income"], pillars_skipped=["expenses"])
        assert p.current_pillar == "assets"

    def test_all_done(self):
        p = UserProfile(user_id=1, pillars_completed=list(PILLAR_ORDER))
        assert p.current_pillar is None

    def test_questions_exist_for_all_pillars(self):
        for pillar in PILLAR_ORDER:
            assert pillar in PILLAR_QUESTIONS


class TestConversationIntegration:
    def test_messages_saved_with_metadata(self):
        uid = _test_user()
        clear_conversation(uid)
        save_message(uid, "user", "I earn 1.1L", {"pillar": "income"})
        msgs = load_conversation(uid)
        assert len(msgs) == 1
        assert msgs[0]["metadata"]["pillar"] == "income"

    def test_profile_persists_across_calls(self):
        uid = _test_user()
        p = UserProfile(user_id=uid, monthly_income=110000, pillars_completed=["income"])
        save_profile(p)
        loaded = load_profile(uid)
        assert loaded.monthly_income == 110000
        assert loaded.current_pillar == "expenses"
