"""initial schema: feature_flags and flag_rules

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-18 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# JSONB on Postgres, generic JSON elsewhere.
JSONVariant = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "feature_flags",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("default_state", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_feature_flags_key", "feature_flags", ["key"], unique=True)

    op.create_table(
        "flag_rules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("flag_id", sa.Integer(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attribute", sa.String(length=128), nullable=False),
        sa.Column("operator", sa.String(length=32), nullable=False),
        sa.Column("values", JSONVariant, nullable=False),
        sa.Column("outcome", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("rollout_percentage", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["flag_id"], ["feature_flags.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("flag_id", "priority", name="uq_flag_rule_priority"),
        sa.CheckConstraint(
            "rollout_percentage IS NULL OR (rollout_percentage >= 0 AND rollout_percentage <= 100)",
            name="ck_rollout_percentage_range",
        ),
    )
    op.create_index("ix_flag_rules_flag_id", "flag_rules", ["flag_id"])


def downgrade() -> None:
    op.drop_index("ix_flag_rules_flag_id", table_name="flag_rules")
    op.drop_table("flag_rules")
    op.drop_index("ix_feature_flags_key", table_name="feature_flags")
    op.drop_table("feature_flags")
