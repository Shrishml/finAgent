"""SQLAlchemy ORM models for all database tables."""
from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Float, Text, DateTime, JSON, ForeignKey, Index, UniqueConstraint
)
from sqlalchemy.orm import declarative_base, relationship
from sqlalchemy.sql import func

Base = declarative_base()


class User(Base):
    """User accounts (Google OAuth)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    google_id = Column(String, unique=True, nullable=False)
    email = Column(String)
    name = Column(String)
    picture = Column(String)
    access_status = Column(String, default="waitlist")
    created_at = Column(DateTime, default=func.now())

    holdings = relationship("Holding", back_populates="user")
    goals = relationship("Goal", back_populates="user")
    assets = relationship("UserAsset", back_populates="user")
    conversations = relationship("Conversation", back_populates="user")
    snapshots = relationship("UserSnapshot", back_populates="user")
    profile = relationship("UserProfile", back_populates="user", uselist=False)


class InviteCode(Base):
    """Invite codes for waitlist access."""
    __tablename__ = "invite_codes"

    code = Column(String, primary_key=True)
    created_at = Column(DateTime, default=func.now())
    max_uses = Column(Integer, default=1)
    used_count = Column(Integer, default=0)
    note = Column(String, default="")


class Holding(Base):
    """Legacy MF holdings table (migrated to user_assets)."""
    __tablename__ = "holdings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    folio = Column(String)
    scheme_name = Column(String)
    data = Column(JSON, nullable=False)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="holdings")

    __table_args__ = (
        UniqueConstraint("user_id", "folio", "scheme_name", name="uq_holdings_user_folio_scheme"),
    )


class NAVCache(Base):
    """Cached NAV data with 24h TTL."""
    __tablename__ = "nav_cache"

    amfi_code = Column(String, primary_key=True)
    nav = Column(Float)
    expense_ratio = Column(Float, default=0)
    scheme_name = Column(String)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())


class NAVHistory(Base):
    """Historical NAV data for funds."""
    __tablename__ = "nav_history"

    amfi_code = Column(String, primary_key=True)
    date = Column(String, primary_key=True)
    nav = Column(Float)


class NAVHistoryMeta(Base):
    """Metadata tracking when NAV history was last fetched."""
    __tablename__ = "nav_history_meta"

    amfi_code = Column(String, primary_key=True)
    last_fetched = Column(String)


class Goal(Base):
    """User financial goals."""
    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String, nullable=False)
    template = Column(String, nullable=False)
    target_amount = Column(Float, nullable=False)
    target_date = Column(String, nullable=False)
    linked_folios = Column(JSON, default=list)
    growth_rate = Column(Float, default=0.10)
    status = Column(String, default="active")
    description = Column(Text, default="")
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="goals")


class UserProfile(Base):
    """Legacy user profile table (migrated to user_assets)."""
    __tablename__ = "user_profiles"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    data = Column(JSON, nullable=False)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="profile")


class Conversation(Base):
    """Chat conversation history."""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    meta = Column("metadata", JSON, default=dict)
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="conversations")

    __table_args__ = (
        Index("idx_conv_user", "user_id", "created_at"),
    )


class UserSnapshot(Base):
    """Financial profile snapshots."""
    __tablename__ = "user_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    snapshot = Column(Text, nullable=False)
    trigger = Column(String, nullable=False, default="onboarding")
    created_at = Column(DateTime, default=func.now())

    user = relationship("User", back_populates="snapshots")

    __table_args__ = (
        Index("idx_snap_user", "user_id", "created_at"),
    )


class UserAsset(Base):
    """Unified asset storage for all financial data types."""
    __tablename__ = "user_assets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    asset_type = Column(String, nullable=False)
    data = Column(JSON, nullable=False)
    source = Column(String, default="declared")
    source_detail = Column(String, default="chat")
    verified_at = Column(DateTime)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())

    user = relationship("User", back_populates="assets")

    __table_args__ = (
        Index("idx_assets_user", "user_id", "asset_type"),
    )
