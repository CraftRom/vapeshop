"""Модулі лояльності та ПІБ одержувача

Revision ID: e5b71c3f9042
Revises: d3a9c05b7e21
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e5b71c3f9042"
down_revision: Union[str, None] = "d3a9c05b7e21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("contact_surname", sa.String(length=128), nullable=True))
    op.add_column("orders", sa.Column("contact_patronymic", sa.String(length=128), nullable=True))


def downgrade() -> None:
    op.drop_column("orders", "contact_patronymic")
    op.drop_column("orders", "contact_surname")
