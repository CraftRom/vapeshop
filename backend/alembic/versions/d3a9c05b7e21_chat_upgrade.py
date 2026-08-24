"""Статус «Прийнято», оператор замовлення, вкладення, активний чат

Revision ID: d3a9c05b7e21
Revises: c7e2b8f41a09
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d3a9c05b7e21"
down_revision: Union[str, None] = "c7e2b8f41a09"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Postgres зберігає статус як ENUM — нове значення треба оголосити явно.
    # Для SQLite Enum зберігається як VARCHAR, тож крок просто пропускається.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TYPE orderstatus ADD VALUE IF NOT EXISTS 'ACCEPTED'")

    op.add_column("orders", sa.Column("operator_id", sa.Integer(), nullable=True))
    op.add_column("orders", sa.Column("operator_name", sa.String(length=128),
                                      nullable=False, server_default=""))

    op.add_column("order_messages", sa.Column("file_id", sa.String(length=255), nullable=True))
    op.add_column("order_messages", sa.Column("file_kind", sa.String(length=16), nullable=True))
    op.add_column("order_messages", sa.Column("file_name", sa.String(length=255), nullable=True))

    op.add_column("users", sa.Column("chat_order_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "chat_order_id")
    op.drop_column("order_messages", "file_name")
    op.drop_column("order_messages", "file_kind")
    op.drop_column("order_messages", "file_id")
    op.drop_column("orders", "operator_name")
    op.drop_column("orders", "operator_id")
    # Значення ENUM у Postgres не видаляється — лишається невживаним
