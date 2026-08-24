"""ТТН і чат замовлення

Revision ID: c7e2b8f41a09
Revises: b2f4a1c93de7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7e2b8f41a09"
down_revision: Union[str, None] = "b2f4a1c93de7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("tracking_number", sa.String(length=64), nullable=True))

    op.create_table(
        "order_messages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=False),
        sa.Column("author", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_order_messages_order_id"), "order_messages", ["order_id"])
    op.create_index(op.f("ix_order_messages_tg_message_id"), "order_messages", ["tg_message_id"])
    op.create_index(op.f("ix_order_messages_created_at"), "order_messages", ["created_at"])
    op.create_index("ix_order_messages_order_created", "order_messages", ["order_id", "created_at"])


def downgrade() -> None:
    op.drop_table("order_messages")
    op.drop_column("orders", "tracking_number")
