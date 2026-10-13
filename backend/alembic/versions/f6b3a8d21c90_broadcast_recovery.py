"""Leased broadcast execution and durable recipient results (F04–F05)."""
from alembic import op
import sqlalchemy as sa

revision = "f6b3a8d21c90"
down_revision = "f2c8a1d96b40"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("broadcasts", sa.Column("unknown_count", sa.Integer(), nullable=False, server_default="0"))
    for name, typ in (("lease_owner", sa.String(64)), ("lease_until", sa.DateTime(timezone=True)),
                      ("heartbeat_at", sa.DateTime(timezone=True)), ("last_error", sa.Text())):
        op.add_column("broadcasts", sa.Column(name, typ, nullable=True))
    op.create_index("ix_broadcasts_recovery", "broadcasts", ["status", "lease_until"])
    op.create_table("broadcast_deliveries",
        sa.Column("broadcast_id", sa.Integer(), sa.ForeignKey("broadcasts.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), primary_key=True),
        sa.Column("tg_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table("broadcast_deliveries")
    op.drop_index("ix_broadcasts_recovery", table_name="broadcasts")
    for name in ("last_error", "heartbeat_at", "lease_until", "lease_owner", "unknown_count"):
        op.drop_column("broadcasts", name)
