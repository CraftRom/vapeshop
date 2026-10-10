"""Visit history, immutable checkout attribution and daily advertising spend."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
revision = "f2c8a1d96b40"
down_revision = "e8b30a2d9071"
branch_labels = None
depends_on = None

def upgrade():
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    op.add_column("orders", sa.Column("attribution", json_type, nullable=True))
    op.create_table("analytics_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attribution", json_type),
        sa.UniqueConstraint("user_id", "session_id", name="uq_analytics_user_session"))
    op.create_index("ix_analytics_sessions_started", "analytics_sessions", ["started_at"])
    op.create_table("marketing_spend",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("source", sa.String(80), nullable=False),
        sa.Column("campaign", sa.String(160), nullable=False, server_default=""),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("day", "source", "campaign", name="uq_marketing_spend_key"))
    op.create_index("ix_marketing_spend_day", "marketing_spend", ["day"])

def downgrade():
    op.drop_table("marketing_spend")
    op.drop_table("analytics_sessions")
    op.drop_column("orders", "attribution")
