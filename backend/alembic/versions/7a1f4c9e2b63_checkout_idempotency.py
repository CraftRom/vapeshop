"""checkout idempotency key

Revision ID: 7a1f4c9e2b63
Revises: 2e7b6a4c9d10
Create Date: 2026-09-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7a1f4c9e2b63"
down_revision: Union[str, None] = "2e7b6a4c9d10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("checkout_key", sa.String(length=64), nullable=True))
    op.create_index("ux_orders_checkout_key", "orders", ["checkout_key"], unique=True)


def downgrade() -> None:
    op.drop_index("ux_orders_checkout_key", table_name="orders")
    op.drop_column("orders", "checkout_key")
