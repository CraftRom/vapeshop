"""Reset bot reachability after separating permanent and transient failures.

Revision ID: d6f8a41e2c73
Revises: c4f7a1d90b52

Before bot 1.6.2 every failed Telegram request set ``bot_reachable = false``.
That included 502, timeout, connection reset and rate limiting, so the database
cannot tell old temporary failures from a real ``chat not found``/blocked user.
Reset once on upgrade. From this revision onward only permanent Bot API errors
set the flag back to false; a successful message or /start sets it to true.
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6f8a41e2c73"
down_revision: Union[str, None] = "c4f7a1d90b52"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    users = sa.table("users", sa.column("bot_reachable", sa.Boolean()))
    op.execute(users.update().where(users.c.bot_reachable.is_(False)).values(bot_reachable=True))


def downgrade() -> None:
    # Старе значення відновити неможливо: ми навмисно відкинули дані, в яких
    # тимчасовий network failure був невідрізнимий від реального блокування.
    pass
