"""Merge migration heads and classify negative SalesDrive outcomes.

Revision ID: e3f7a91c2d64
Revises: 9c2f1b7e4d31, d8b6f20a1c44
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e3f7a91c2d64"
down_revision: Union[str, tuple[str, str], None] = ("9c2f1b7e4d31", "d8b6f20a1c44")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _status_name_expr(dialect: str) -> str:
    if dialect == "postgresql":
        snapshot_name = "NULLIF(TRIM(crm_snapshot ->> 'statusName'), '')"
    elif dialect == "sqlite":
        snapshot_name = "NULLIF(TRIM(json_extract(crm_snapshot, '$.statusName')), '')"
    else:
        snapshot_name = "NULL"
    return f"COALESCE(NULLIF(TRIM(crm_status_name), ''), {snapshot_name}, '')"


def upgrade() -> None:
    status_name = _status_name_expr(op.get_bind().dialect.name)
    sale_names = "'Продаж','продаж','ПРОДАЖ','sale','Sale','SALE'"
    refusal_names = (
        "'Відмова','відмова','ВІДМОВА',"
        "'Повернення','повернення','ПОВЕРНЕННЯ','Повернено','повернено','ПОВЕРНЕНО',"
        "'Видалений','видалений','ВИДАЛЕНИЙ','Видалено','видалено','ВИДАЛЕНО',"
        "'refusal','Refusal','REFUSAL','return','Return','RETURN',"
        "'returned','Returned','RETURNED','deleted','Deleted','DELETED'"
    )

    # Не переобчислюємо невідомі CRM-статуси. business_state уже є
    # persisted source of truth; його не можна скидати в pending лише через
    # тимчасово нерозв'язану назву. Перекласифіковуємо тільки статуси, для
    # яких семантика однозначна.
    op.execute(sa.text(f"""
        UPDATE orders
        SET business_state = 'refusal',
            business_state_at = COALESCE(crm_fetched_at, crm_synced_at, updated_at, created_at)
        WHERE {status_name} IN ({refusal_names})
          AND COALESCE(business_state, 'pending') <> 'refusal'
    """))
    op.execute(sa.text(f"""
        UPDATE orders
        SET business_state = 'sale',
            business_state_at = COALESCE(crm_fetched_at, crm_synced_at, updated_at, created_at)
        WHERE {status_name} IN ({sale_names})
          AND COALESCE(business_state, 'pending') <> 'sale'
    """))

    # Rebuild denormalized customer totals after reclassification. A row that
    # became refusal/return/deleted must disappear from purchase counters.
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
    # The merge itself is structural. Reverting the refined classification
    # would knowingly restore wrong statistics, so data is left untouched.
    pass
