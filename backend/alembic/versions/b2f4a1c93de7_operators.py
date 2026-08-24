"""Оператори панелі

Revision ID: b2f4a1c93de7
Revises: 8d61348a9ac8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2f4a1c93de7"
down_revision: Union[str, None] = "8d61348a9ac8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "operators",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("login", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="operator"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_operators_login"), "operators", ["login"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_operators_login"), table_name="operators")
    op.drop_table("operators")
