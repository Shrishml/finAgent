"""User CRUD operations."""
import logging

from sqlalchemy import select

from finagent.storage.database import get_db
from finagent.storage.models import User

log = logging.getLogger("finagent.storage")


async def get_or_create_user(google_id: str, email: str = "", name: str = "", picture: str = "") -> int:
    """Get existing user or create new one. Returns user_id."""
    async with get_db() as db:
        result = await db.execute(select(User).where(User.google_id == google_id))
        user = result.scalar_one_or_none()
        if user:
            user.email = email
            user.name = name
            user.picture = picture
            return user.id
        new_user = User(google_id=google_id, email=email, name=name, picture=picture)
        db.add(new_user)
        await db.flush()
        return new_user.id


async def get_user_name(user_id: int) -> str:
    """Get user's display name by user_id."""
    async with get_db() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        return user.name if user and user.name else ""
