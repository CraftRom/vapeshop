"""Списки бажаного

Revision ID: f8c1d29e4a73
Revises: e5b71c3f9042
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "f8c1d29e4a73"
down_revision: Union[str, None] = "e5b71c3f9042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wishlists",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("product_ids", JSONB().with_variant(sa.JSON(), "sqlite"),
                  nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_wishlists_user_id"), "wishlists", ["user_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_wishlists_user_id"), table_name="wishlists")
    op.drop_table("wishlists")
