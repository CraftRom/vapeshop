"""Чи доходять до клієнта повідомлення бота

Revision ID: c4f7a1d90b52
Revises: b6e2f0a17c34

У Mini App можна зайти з групи, купити й жодного разу не натиснути
«Старт» — приватного чату з ботом тоді немає, і Telegram відповідає
«chat not found». Наявні клієнти позначаються досяжними: інакше кожен із
них одразу побачив би попередження, хоч у них усе працює.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c4f7a1d90b52"
down_revision: Union[str, None] = "b6e2f0a17c34"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column(
        "bot_reachable", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("users", "bot_reachable")
