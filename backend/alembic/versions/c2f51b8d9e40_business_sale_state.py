"""Canonical business state for sales statistics.

Revision ID: c2f51b8d9e40
Revises: 7a1f4c9e2b63
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c2f51b8d9e40"
down_revision: Union[str, None] = "7a1f4c9e2b63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("business_state", sa.String(length=16), nullable=False, server_default="pending"),
    )
    op.add_column(
        "orders",
        sa.Column("business_state_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_orders_business_state", "orders", ["business_state"], unique=False)
    op.create_index("ix_orders_business_state_at", "orders", ["business_state_at"], unique=False)
    op.create_index(
        "ix_orders_business_state_event",
        "orders",
        ["business_state", "business_state_at"],
        unique=False,
    )

    bind = op.get_bind()
    dialect = bind.dialect.name
    # Старі snapshot можуть уже містити правильну назву статусу, навіть якщо
    # crm_status_name колись не був заповнений. Синтаксис JSON різний лише тут.
    if dialect == "postgresql":
        snapshot_name = "NULLIF(TRIM(crm_snapshot ->> 'statusName'), '')"
    elif dialect == "sqlite":
        snapshot_name = "NULLIF(TRIM(json_extract(crm_snapshot, '$.statusName')), '')"
    else:
        snapshot_name = "NULL"

    status_name = f"COALESCE(NULLIF(TRIM(crm_status_name), ''), {snapshot_name})"
    op.execute(sa.text(f"""
        UPDATE orders
        SET business_state = CASE
            WHEN {status_name} = 'Продаж' THEN 'sale'
            WHEN {status_name} = 'Відмова' THEN 'refusal'
            WHEN crm_id IS NULL AND crm_status_id IS NULL AND COALESCE(crm_state, '') = '' AND status = 'DONE' THEN 'sale'
            WHEN crm_id IS NULL AND crm_status_id IS NULL AND COALESCE(crm_state, '') = '' AND status = 'CANCELLED' THEN 'refusal'
            ELSE 'pending'
        END
    """))
    op.execute(sa.text("""
        UPDATE orders
        SET business_state_at = CASE
            WHEN business_state IN ('sale', 'refusal')
                THEN COALESCE(crm_fetched_at, crm_synced_at, updated_at, created_at)
            ELSE created_at
        END
    """))

    # Старі orders_count/total_spent рахували PAID/SHIPPED як покупки. Після
    # введення канонічного sale це було б систематично завищено, тому одразу
    # перебудовуємо денормалізовані totals із нового джерела істини.
    op.execute(sa.text("""
        UPDATE users
        SET orders_count = COALESCE((
                SELECT COUNT(*) FROM orders
                WHERE orders.user_id = users.id AND orders.business_state = 'sale'
            ), 0),
            total_spent = COALESCE((
                SELECT SUM(orders.total) FROM orders
                WHERE orders.user_id = users.id AND orders.business_state = 'sale'
            ), 0)
    """))


def downgrade() -> None:
    op.drop_index("ix_orders_business_state_event", table_name="orders")
    op.drop_index("ix_orders_business_state_at", table_name="orders")
    op.drop_index("ix_orders_business_state", table_name="orders")
    op.drop_column("orders", "business_state_at")
    op.drop_column("orders", "business_state")
