"""Unit tests for goal model and storage."""
import os
import pytest
from datetime import date, timedelta
from finagent.models.goal import Goal, GOAL_TEMPLATES
from finagent.storage import sqlite as db


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    """Use a temp database for each test."""
    monkeypatch.setattr(db, "_DB_DIR", tmp_path)
    monkeypatch.setattr(db, "_DB_PATH", tmp_path / "test.db")


@pytest.fixture
def user_id():
    return db.get_or_create_user("test-google-id", "test@test.com", "Test User")


class TestGoalModel:
    def test_template_default_growth(self):
        g = Goal(user_id=1, name="Retire", template="retirement", target_amount=5_000_000, target_date="2035-01-01")
        assert g.growth_rate == 0.12

    def test_custom_growth_override(self):
        g = Goal(user_id=1, name="House", template="house", target_amount=1_000_000, target_date="2030-01-01", growth_rate=0.15)
        assert g.growth_rate == 0.15

    def test_all_templates_have_defaults(self):
        for key, tmpl in GOAL_TEMPLATES.items():
            assert "label" in tmpl
            assert 0 < tmpl["default_growth"] <= 0.20


class TestGoalStorage:
    def test_create_and_load(self, user_id):
        g = Goal(user_id=user_id, name="Retirement", template="retirement", target_amount=5_000_000, target_date="2035-01-01", linked_folios=["F1/Scheme A"])
        gid = db.save_goal(g)
        assert gid > 0

        goals = db.load_goals(user_id)
        assert len(goals) == 1
        assert goals[0].name == "Retirement"
        assert goals[0].linked_folios == ["F1/Scheme A"]
        assert goals[0].growth_rate == 0.12

    def test_update(self, user_id):
        g = Goal(user_id=user_id, name="House", template="house", target_amount=1_000_000, target_date="2030-01-01")
        gid = db.save_goal(g)

        g.id = gid
        g.target_amount = 2_000_000
        db.save_goal(g)

        goals = db.load_goals(user_id)
        assert len(goals) == 1
        assert goals[0].target_amount == 2_000_000

    def test_delete(self, user_id):
        gid = db.save_goal(Goal(user_id=user_id, name="Trip", template="travel", target_amount=100_000, target_date="2027-01-01"))
        assert db.delete_goal(gid, user_id) is True
        assert db.load_goals(user_id) == []

    def test_delete_wrong_user(self, user_id):
        gid = db.save_goal(Goal(user_id=user_id, name="Trip", template="travel", target_amount=100_000, target_date="2027-01-01"))
        assert db.delete_goal(gid, user_id + 999) is False
        assert len(db.load_goals(user_id)) == 1

    def test_clear_goals(self, user_id):
        db.save_goal(Goal(user_id=user_id, name="A", template="custom", target_amount=1, target_date="2030-01-01"))
        db.save_goal(Goal(user_id=user_id, name="B", template="custom", target_amount=2, target_date="2030-01-01"))
        db.clear_goals(user_id)
        assert db.load_goals(user_id) == []

    def test_multiple_goals(self, user_id):
        db.save_goal(Goal(user_id=user_id, name="Retire", template="retirement", target_amount=5_000_000, target_date="2035-01-01"))
        db.save_goal(Goal(user_id=user_id, name="House", template="house", target_amount=1_000_000, target_date="2030-01-01"))
        db.save_goal(Goal(user_id=user_id, name="Emergency", template="emergency", target_amount=300_000, target_date="2026-06-01"))
        assert len(db.load_goals(user_id)) == 3

    def test_isolation_between_users(self, user_id):
        user2 = db.get_or_create_user("other-google-id", "other@test.com", "Other")
        db.save_goal(Goal(user_id=user_id, name="Mine", template="custom", target_amount=1, target_date="2030-01-01"))
        db.save_goal(Goal(user_id=user2, name="Theirs", template="custom", target_amount=2, target_date="2030-01-01"))
        assert len(db.load_goals(user_id)) == 1
        assert len(db.load_goals(user2)) == 1
        assert db.load_goals(user_id)[0].name == "Mine"
