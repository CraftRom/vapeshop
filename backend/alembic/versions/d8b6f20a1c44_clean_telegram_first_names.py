"""remove Telegram handles accidentally stored as first_name

Revision ID: d8b6f20a1c44
Revises: c2f51b8d9e40
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d8b6f20a1c44"
down_revision: Union[str, None] = "c2f51b8d9e40"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Background CRM read-side refresh filters by this field every minute.
    op.create_index("ix_orders_crm_fetched_at", "orders", ["crm_fetched_at"], unique=False)

    # Username is retained in users.username. We only remove the false claim
    # that @handle is a person's given name; a real name cannot be inferred.
    op.execute("UPDATE users SET first_name = NULL WHERE TRIM(first_name) LIKE '@%'")


def downgrade() -> None:
    op.drop_index("ix_orders_crm_fetched_at", table_name="orders")
    # Destructive profile repair cannot be reconstructed safely.
