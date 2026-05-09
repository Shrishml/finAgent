"""User CRUD operations."""
import logging
import secrets

from sqlalchemy import select, update

from finagent.storage.database import get_db
from finagent.storage.models import User, InviteCode

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


async def get_user_access_status(user_id: int) -> str:
    """Returns 'waitlist', 'active', or 'blocked'."""
    async with get_db() as db:
        result = await db.execute(select(User.access_status).where(User.id == user_id))
        status = result.scalar_one_or_none()
        return status if status else "waitlist"


async def set_user_access_status(user_id: int, status: str) -> None:
    """Set user's access status."""
    async with get_db() as db:
        await db.execute(update(User).where(User.id == user_id).values(access_status=status))


async def list_waitlist_users() -> list[dict]:
    """List all users on waitlist."""
    async with get_db() as db:
        result = await db.execute(
            select(User.id, User.email, User.name, User.created_at)
            .where(User.access_status == "waitlist")
            .order_by(User.created_at)
        )
        return [{"id": r[0], "email": r[1], "name": r[2], "created_at": str(r[3])} for r in result.fetchall()]


async def redeem_invite_code(code: str, user_id: int) -> bool:
    """Redeem an invite code. Returns True if successful."""
    async with get_db() as db:
        result = await db.execute(select(InviteCode).where(InviteCode.code == code))
        invite = result.scalar_one_or_none()
        if not invite or invite.used_count >= invite.max_uses:
            return False
        invite.used_count += 1
        await db.execute(update(User).where(User.id == user_id).values(access_status="active"))
        return True


async def create_invite_codes(count: int = 5, max_uses: int = 1, note: str = "") -> list[str]:
    """Create new invite codes."""
    async with get_db() as db:
        codes = []
        for _ in range(count):
            code = f"ARTH-{secrets.token_hex(3).upper()}"
            db.add(InviteCode(code=code, max_uses=max_uses, note=note))
            codes.append(code)
        return codes


async def list_invite_codes() -> list[dict]:
    """List all invite codes."""
    async with get_db() as db:
        result = await db.execute(select(InviteCode).order_by(InviteCode.created_at.desc()))
        return [
            {
                "code": c.code,
                "created_at": str(c.created_at),
                "max_uses": c.max_uses,
                "used_count": c.used_count,
                "note": c.note,
            }
            for c in result.scalars().all()
        ]
