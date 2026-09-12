"""panel notification center

Revision ID: 9d2e6f41a7bc
Revises: 4b8f0c2d91aa
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "9d2e6f41a7bc"
down_revision: Union[str, None] = "4b8f0c2d91aa"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "panel_notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("body", sa.Text(), nullable=False, server_default=""),
        sa.Column("href", sa.String(length=512), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("actor", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_panel_notifications_kind", "panel_notifications", ["kind"])
    op.create_index("ix_panel_notifications_created", "panel_notifications", ["created_at"])
    op.create_index("ix_panel_notifications_kind_created", "panel_notifications", ["kind", "created_at"])

    op.create_table(
        "panel_notification_reads",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("notification_id", sa.Integer(), sa.ForeignKey("panel_notifications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("viewer_key", sa.String(length=64), nullable=False),
        sa.Column("read_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("notification_id", "viewer_key", name="uq_panel_notification_read"),
    )
    op.create_index("ix_panel_notification_reads_notification_id", "panel_notification_reads", ["notification_id"])
    op.create_index("ix_panel_notification_reads_viewer", "panel_notification_reads", ["viewer_key", "notification_id"])


def downgrade() -> None:
    op.drop_table("panel_notification_reads")
    op.drop_table("panel_notifications")
