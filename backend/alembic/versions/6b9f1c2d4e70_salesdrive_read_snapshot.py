"""SalesDrive read-side snapshot for linked orders only.

revision: 6b9f1c2d4e70
revises: 4f7c2a91d6e0
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "6b9f1c2d4e70"
down_revision = "4f7c2a91d6e0"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("orders", sa.Column("crm_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("orders", sa.Column("crm_fetched_at", sa.DateTime(timezone=True), nullable=True))

def downgrade():
    op.drop_column("orders", "crm_fetched_at")
    op.drop_column("orders", "crm_snapshot")
