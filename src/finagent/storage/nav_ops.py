"""NAV cache operations."""
from datetime import datetime, timedelta

from sqlalchemy import select

from finagent.storage.database import get_db
from finagent.storage.models import NAVCache


async def save_nav_cache(amfi_code: str, nav: float, scheme_name: str = "", expense_ratio: float = 0):
    """Save or update NAV cache entry."""
    async with get_db() as db:
        result = await db.execute(select(NAVCache).where(NAVCache.amfi_code == amfi_code))
        existing = result.scalar_one_or_none()
        if existing:
            existing.nav = nav
            existing.expense_ratio = expense_ratio
            existing.scheme_name = scheme_name
            existing.updated_at = datetime.utcnow()
        else:
            entry = NAVCache(
                amfi_code=amfi_code,
                nav=nav,
                expense_ratio=expense_ratio,
                scheme_name=scheme_name
            )
            db.add(entry)


async def get_cached_nav(amfi_code: str) -> dict | None:
    """Get cached data if less than 24h old. Returns {nav, expense_ratio} or None."""
    async with get_db() as db:
        cutoff = datetime.utcnow() - timedelta(hours=24)
        result = await db.execute(
            select(NAVCache).where(
                NAVCache.amfi_code == amfi_code,
                NAVCache.updated_at > cutoff
            )
        )
        entry = result.scalar_one_or_none()
        if entry:
            return {"nav": entry.nav, "expense_ratio": entry.expense_ratio}
        return None
