"""Спільний облік накладних і синхронізації з SalesDrive.

Revision ID: a7c3e1f5d2b9
Revises: 9d2e6f41a7bc

Поля лягають у саму таблицю замовлень, а не в окрему таблицю інтеграції.
Замовлення одне — і в панелі, і в боті, і в SalesDrive; накладна одна —
хоч створена кнопкою в панелі, хоч менеджером у SalesDrive, хоч вписана
руками. Окрема таблиця «SalesDrive-замовлень» означала б другу копію тих
самих даних, яка рано чи пізно розійдеться з першою.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a7c3e1f5d2b9"
down_revision: Union[str, None] = "9d2e6f41a7bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("orders") as batch:
        # Накладна: номер уже є (tracking_number). Ref потрібен, щоб
        # видалити чи роздрукувати ТТН, створену через API Нової пошти;
        # джерело — щоб знати, чи можна її видаляти звідси.
        batch.add_column(sa.Column("waybill_ref", sa.String(64), nullable=True))
        batch.add_column(sa.Column("waybill_source", sa.String(16), nullable=True))
        batch.add_column(sa.Column("waybill_cost", sa.Numeric(12, 2), nullable=True))
        # Синхронізація з CRM. crm_id — номер заявки в SalesDrive: вебхук
        # приходить саме з ним. crm_state — черга: pending, creating,
        # synced, failed. Стан живе в тому ж рядку, що й замовлення, тож
        # «змінили статус і впали до відправки в CRM» неможливо: позначка
        # pending пишеться тією самою транзакцією, що й статус.
        batch.add_column(sa.Column("crm_id", sa.String(32), nullable=True))
        batch.add_column(sa.Column("crm_state", sa.String(16), nullable=False, server_default=""))
        batch.add_column(sa.Column("crm_error", sa.String(512), nullable=True))
        batch.add_column(sa.Column("crm_attempts", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("crm_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_orders_crm_id", "orders", ["crm_id"])
    op.create_index("ix_orders_crm_state", "orders", ["crm_state"])


def downgrade() -> None:
    op.drop_index("ix_orders_crm_state", table_name="orders")
    op.drop_index("ix_orders_crm_id", table_name="orders")
    with op.batch_alter_table("orders") as batch:
        for column in ("crm_synced_at", "crm_attempts", "crm_error", "crm_state",
                       "crm_id", "waybill_cost", "waybill_source", "waybill_ref"):
            batch.drop_column(column)
