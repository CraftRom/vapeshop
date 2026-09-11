"""General customer support threads for /ask and dashboard inbox.

Revision ID: f1a9c4e7b2d6
Revises: d6f8a41e2c73
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a9c4e7b2d6"
down_revision: Union[str, None] = "d6f8a41e2c73"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.create_table(
        "support_threads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_support_threads_user_id", "support_threads", ["user_id"], unique=True)
    op.create_index("ix_support_threads_status", "support_threads", ["status"])
    op.create_index("ix_support_threads_updated_at", "support_threads", ["updated_at"])
    op.create_index("ix_support_threads_last_message_at", "support_threads", ["last_message_at"])

    op.create_table(
        "support_messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("thread_id", sa.Integer(), sa.ForeignKey("support_threads.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("direction", sa.String(length=4), nullable=False),
        sa.Column("author", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=True),
        sa.Column("file_id", sa.String(length=255), nullable=True),
        sa.Column("file_kind", sa.String(length=16), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=True),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_support_messages_thread_id", "support_messages", ["thread_id"])
    op.create_index("ix_support_messages_user_id", "support_messages", ["user_id"])
    op.create_index("ix_support_messages_tg_message_id", "support_messages", ["tg_message_id"])
    op.create_index("ix_support_messages_created_at", "support_messages", ["created_at"])
    op.create_index(
        "ix_support_messages_thread_created",
        "support_messages", ["thread_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("support_messages")
    op.drop_table("support_threads")
