"""Goal CRUD operations."""
import logging

from sqlalchemy import select, delete

from finagent.storage.database import get_db
from finagent.storage.models import Goal as GoalModel
from finagent.models.goal import Goal

log = logging.getLogger("finagent.storage")


async def save_goal(goal: Goal) -> int:
    """Insert or update a goal. Returns goal id."""
    async with get_db() as db:
        if goal.id:
            result = await db.execute(
                select(GoalModel).where(
                    GoalModel.id == goal.id,
                    GoalModel.user_id == goal.user_id
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                existing.name = goal.name
                existing.template = goal.template
                existing.target_amount = goal.target_amount
                existing.target_date = goal.target_date
                existing.linked_folios = goal.linked_folios
                existing.growth_rate = goal.growth_rate
                existing.status = goal.status
                existing.description = goal.description
                return goal.id
        new_goal = GoalModel(
            user_id=goal.user_id,
            name=goal.name,
            template=goal.template,
            target_amount=goal.target_amount,
            target_date=goal.target_date,
            linked_folios=goal.linked_folios,
            growth_rate=goal.growth_rate,
            status=goal.status,
            description=goal.description
        )
        db.add(new_goal)
        await db.flush()
        return new_goal.id


async def load_goals(user_id: int) -> list[Goal]:
    """Load all goals for a user."""
    async with get_db() as db:
        result = await db.execute(select(GoalModel).where(GoalModel.user_id == user_id))
        rows = result.scalars().all()
        return [
            Goal(
                id=r.id,
                user_id=r.user_id,
                name=r.name,
                template=r.template,
                target_amount=r.target_amount,
                target_date=r.target_date,
                linked_folios=r.linked_folios or [],
                growth_rate=r.growth_rate,
                created_at=r.created_at.isoformat() if r.created_at else "",
                status=r.status or "active",
                description=r.description or ""
            )
            for r in rows
        ]


async def delete_goal(goal_id: int, user_id: int) -> bool:
    """Delete a goal. Returns True if deleted."""
    async with get_db() as db:
        result = await db.execute(
            delete(GoalModel).where(
                GoalModel.id == goal_id,
                GoalModel.user_id == user_id
            )
        )
        return result.rowcount > 0


async def clear_goals(user_id: int):
    """Clear all goals for a user."""
    async with get_db() as db:
        await db.execute(delete(GoalModel).where(GoalModel.user_id == user_id))
