"""storage lifecycle: compressed cold messages and notification read cursor

Revision ID: b8f2c6d4a910
Revises: f4c91a7d2b60
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "b8f2c6d4a910"
down_revision = "f4c91a7d2b60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "message_archives",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("raw_bytes", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("min_message_id", sa.Integer(), nullable=True),
        sa.Column("max_message_id", sa.Integer(), nullable=True),
        sa.Column("first_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("codec", sa.String(length=24), nullable=False, server_default="gzip-json-v1"),
        sa.Column("payload", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("kind", "entity_id", name="uq_message_archive_entity"),
    )
    op.create_table(
        "archived_message_refs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("tg_message_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("kind", "user_id", "tg_message_id", name="uq_archived_message_ref"),
    )
    op.create_index("ix_archived_message_refs_entity_id", "archived_message_refs", ["entity_id"])

    op.create_table(
        "panel_notification_cursors",
        sa.Column("viewer_key", sa.String(length=64), primary_key=True),
        sa.Column("through_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    # History API pages by monotonic message id. The old (entity, created_at)
    # index remains useful for chronology, but (entity, id) avoids sorting for
    # after_id / before_id pagination on long conversations.
    op.create_index(
        "ix_order_messages_order_id_id", "order_messages", ["order_id", "id"]
    )
    op.create_index(
        "ix_support_messages_thread_id_id", "support_messages", ["thread_id", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_support_messages_thread_id_id", table_name="support_messages")
    op.drop_index("ix_order_messages_order_id_id", table_name="order_messages")
    op.drop_table("panel_notification_cursors")
    op.drop_index("ix_archived_message_refs_entity_id", table_name="archived_message_refs")
    op.drop_table("archived_message_refs")
    op.drop_table("message_archives")
