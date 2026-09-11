"""Multiple retained support sessions per customer.

Revision ID: 0c5a6d91e7f2
Revises: f1a9c4e7b2d6
"""
from typing import Union

from alembic import op


revision: str = "0c5a6d91e7f2"
down_revision: Union[str, None] = "f1a9c4e7b2d6"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    # Раніше user_id був UNIQUE і кожний /ask перевідкривав одну довгу
    # стрічку. Тепер закритий чат є незмінною історією, а новий /ask
    # створює нову сесію. Сам індекс лишається, але вже не унікальний.
    op.drop_index("ix_support_threads_user_id", table_name="support_threads")
    op.create_index(
        "ix_support_threads_user_id", "support_threads", ["user_id"], unique=False
    )
    op.create_index(
        "ix_support_threads_user_status_updated",
        "support_threads",
        ["user_id", "status", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    # Downgrade можливий лише коли на кожного клієнта знову лишився один
    # thread; інакше БД коректно відмовить створювати UNIQUE індекс замість
    # мовчки видаляти історію.
    op.drop_index("ix_support_threads_user_status_updated", table_name="support_threads")
    op.drop_index("ix_support_threads_user_id", table_name="support_threads")
    op.create_index(
        "ix_support_threads_user_id", "support_threads", ["user_id"], unique=True
    )
