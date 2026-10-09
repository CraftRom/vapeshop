"""Revocable browser sessions and operator credential versions."""
from alembic import op
import sqlalchemy as sa
revision = "e8b30a2d9071"
down_revision = "d7a24c10b853"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("operators", sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("dashboard_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("operator_id", sa.Integer(), nullable=False),
        sa.Column("login", sa.String(64), nullable=False),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("auth_version", sa.Integer(), nullable=False),
        sa.Column("owner_fingerprint", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_dashboard_sessions_operator_id", "dashboard_sessions", ["operator_id"])
    op.create_index("ix_dashboard_sessions_expires_at", "dashboard_sessions", ["expires_at"])

def downgrade():
    op.drop_table("dashboard_sessions")
    op.drop_column("operators", "auth_version")
