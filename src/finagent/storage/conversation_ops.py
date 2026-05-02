"""Conversation/chat history operations."""
from sqlalchemy import select, delete, desc

from finagent.storage.database import get_db
from finagent.storage.models import Conversation

_MAX_MESSAGES_PER_USER = 50


async def save_message(user_id: int, role: str, content: str, metadata: dict | None = None):
    """Save a conversation message. Auto-prunes to keep last N messages."""
    async with get_db() as db:
        msg = Conversation(
            user_id=user_id,
            role=role,
            content=content,
            meta=metadata or {}
        )
        db.add(msg)
        await db.flush()

        # Get IDs to keep
        keep_result = await db.execute(
            select(Conversation.id)
            .where(Conversation.user_id == user_id)
            .order_by(desc(Conversation.created_at))
            .limit(_MAX_MESSAGES_PER_USER)
        )
        keep_ids = [r[0] for r in keep_result.all()]

        # Delete old messages not in keep list
        if keep_ids:
            await db.execute(
                delete(Conversation).where(
                    Conversation.user_id == user_id,
                    Conversation.id.notin_(keep_ids)
                )
            )


async def load_conversation(user_id: int, limit: int = 20) -> list[dict]:
    """Load recent conversation messages, oldest first."""
    async with get_db() as db:
        result = await db.execute(
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(desc(Conversation.created_at))
            .limit(limit)
        )
        rows = result.scalars().all()

        return [
            {
                "role": r.role,
                "content": r.content,
                "metadata": r.meta or {},
                "created_at": r.created_at.isoformat() if r.created_at else None
            }
            for r in reversed(rows)  # reverse to get oldest-first
        ]


async def clear_conversation(user_id: int):
    """Clear all conversation history for a user."""
    async with get_db() as db:
        await db.execute(delete(Conversation).where(Conversation.user_id == user_id))
