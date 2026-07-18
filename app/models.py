"""SQLAlchemy ORM models for feature flags and their rules."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)

# JSONB on Postgres, generic JSON elsewhere (e.g. SQLite in tests).
JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    # Global kill-switch: when false the flag always evaluates OFF.
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Fallback outcome when no rule matches.
    default_state: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    rules: Mapped[list[FlagRule]] = relationship(
        back_populates="flag",
        cascade="all, delete-orphan",
        order_by="FlagRule.priority",
        lazy="selectin",
    )


class FlagRule(Base):
    __tablename__ = "flag_rules"
    __table_args__ = (
        UniqueConstraint("flag_id", "priority", name="uq_flag_rule_priority"),
        CheckConstraint(
            "rollout_percentage IS NULL OR (rollout_percentage >= 0 AND rollout_percentage <= 100)",
            name="ck_rollout_percentage_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    flag_id: Mapped[int] = mapped_column(
        ForeignKey("feature_flags.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Lower priority evaluates first; first match wins.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    attribute: Mapped[str] = mapped_column(String(128), nullable=False)
    operator: Mapped[str] = mapped_column(String(32), nullable=False)
    # Comparison operands, stored as a JSON array.
    values: Mapped[list] = mapped_column(JSONVariant, nullable=False, default=list)
    # Outcome returned when this rule matches (subject to rollout gating).
    outcome: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Optional deterministic percentage rollout (0-100).
    rollout_percentage: Mapped[int | None] = mapped_column(Integer, nullable=True)

    flag: Mapped[FeatureFlag] = relationship(back_populates="rules")
