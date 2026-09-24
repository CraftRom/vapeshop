"""Persist complete order-chat delivery history.

Revision ID: f4c91a7d2b60
Revises: e3f7a91c2d64
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4c91a7d2b60"
down_revision: Union[str, None] = "e3f7a91c2d64"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("order_messages", sa.Column("delivered", sa.Boolean(), nullable=True))
    op.add_column("order_messages", sa.Column("delivery_error", sa.String(length=255), nullable=True))
    # Старі вихідні повідомлення з Telegram message_id були реально прийняті
    # Bot API. Інші старі записи лишаємо unknown, а не вигадуємо стан.
    op.execute(sa.text("""
        UPDATE order_messages
        SET delivered = TRUE
        WHERE direction = 'out' AND tg_message_id IS NOT NULL
    """))


def downgrade() -> None:
    op.drop_column("order_messages", "delivery_error")
    op.drop_column("order_messages", "delivered")
