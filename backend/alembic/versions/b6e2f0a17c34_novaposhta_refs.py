"""Спосіб доставки й коди довідника Нової пошти

Revision ID: b6e2f0a17c34
Revises: a9d4e77b1c60

Колонки nullable і лишаються порожніми в наявних замовленнях: вигадати
коди відділень заднім числом за текстом «Київ, НП 12» неможливо — під цей
опис у Києві підходить і відділення №12, і поштомат №12, і №120.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b6e2f0a17c34"
down_revision: Union[str, None] = "a9d4e77b1c60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("delivery_method", sa.String(length=16), nullable=True))
    op.add_column("orders", sa.Column("delivery_city_ref", sa.String(length=64), nullable=True))
    op.add_column("orders", sa.Column("delivery_warehouse_ref", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "delivery_warehouse_ref")
    op.drop_column("orders", "delivery_city_ref")
    op.drop_column("orders", "delivery_method")
