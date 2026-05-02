"""User snapshot operations."""
from datetime import datetime, timedelta

from sqlalchemy import select, delete, desc

from finagent.storage.database import get_db
from finagent.storage.models import UserSnapshot


async def save_snapshot(user_id: int, snapshot: str, trigger: str = "onboarding") -> int:
    """Save a new snapshot. Returns snapshot id."""
    async with get_db() as db:
        snap = UserSnapshot(
            user_id=user_id,
            snapshot=snapshot,
            trigger=trigger
        )
        db.add(snap)
        await db.flush()
        return snap.id


async def get_latest_snapshot(user_id: int) -> dict | None:
    """Get most recent snapshot for user."""
    async with get_db() as db:
        result = await db.execute(
            select(UserSnapshot)
            .where(UserSnapshot.user_id == user_id)
            .order_by(desc(UserSnapshot.created_at))
            .limit(1)
        )
        snap = result.scalar_one_or_none()

        if not snap:
            return None
        return {
            "id": snap.id,
            "snapshot": snap.snapshot,
            "trigger": snap.trigger,
            "created_at": snap.created_at.isoformat() if snap.created_at else None
        }


async def should_update_snapshot(user_id: int, profile_updated_at: str | None = None) -> tuple[bool, str]:
    """Check if snapshot needs regeneration. Returns (should_update, reason)."""
    from finagent.storage.profile_ops import load_profile

    snap = await get_latest_snapshot(user_id)
    profile = await load_profile(user_id)
    if not profile:
        return False, ""
    has_data = profile.monthly_income > 0 or profile.monthly_expenses > 0 or profile.age > 0
    if not snap:
        return (True, "first_snapshot") if has_data else (False, "")

    snap_time = snap["created_at"]
    if isinstance(snap_time, str):
        snap_time = datetime.fromisoformat(snap_time.replace("Z", "+00:00"))

    now = datetime.utcnow()
    if (now - snap_time.replace(tzinfo=None)).days > 30:
        return True, "stale"
    return False, ""


async def clear_snapshots(user_id: int):
    """Clear all snapshots for a user."""
    async with get_db() as db:
        await db.execute(delete(UserSnapshot).where(UserSnapshot.user_id == user_id))
