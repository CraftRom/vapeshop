"""Відкладені розсилки

Додає час запуску й індекс, за яким планувальник щогодини вибирає дозрілі
розсилки. Статус SCHEDULED додається до наявного enum-типу: SQLAlchemy пише в стовпець
імена членів enum'а (SCHEDULED), а не їхні значення (scheduled).

Revision ID: a1c74e35b806
Revises: f8c1d29e4a73
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c74e35b806"
down_revision: Union[str, None] = "f8c1d29e4a73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Postgres зберігає enum окремим типом і новим значенням його треба вчити
# явно. SQLite тримає enum як VARCHAR, і там цей крок зайвий — тому
# перевіряємо діалект, а не виконуємо наосліп.
_ENUM_NAME = "broadcaststatus"
_NEW_VALUE = "SCHEDULED"


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        # IF NOT EXISTS — щоб повторний запуск міграції не падав
        op.execute(f"ALTER TYPE {_ENUM_NAME} ADD VALUE IF NOT EXISTS '{_NEW_VALUE}'")

    op.add_column(
        "broadcasts",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_broadcasts_due", "broadcasts", ["status", "scheduled_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_broadcasts_due", table_name="broadcasts")
    op.drop_column("broadcasts", "scheduled_at")
    # Значення enum'а в Postgres не видаляємо: DROP VALUE не існує, а
    # перестворення типу зачепило б наявні рядки. Зайве значення нікому не
    # заважає.
