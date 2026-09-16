"""SalesDrive authoritative order status

Revision ID: 4f7c2a91d6e0
Revises: a7c3e1f5d2b9, 9c2f1b7e4d31
"""
from alembic import op
import sqlalchemy as sa

revision = "4f7c2a91d6e0"
down_revision = ("a7c3e1f5d2b9", "9c2f1b7e4d31")
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("orders", sa.Column("crm_status_id", sa.String(32), nullable=True))
    op.add_column("orders", sa.Column("crm_status_name", sa.String(128), nullable=True))
    op.create_index("ix_orders_crm_status_id", "orders", ["crm_status_id"])

def downgrade():
    op.drop_index("ix_orders_crm_status_id", table_name="orders")
    op.drop_column("orders", "crm_status_name")
    op.drop_column("orders", "crm_status_id")
