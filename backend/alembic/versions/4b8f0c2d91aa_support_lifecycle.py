"""Strict lifecycle for retained support sessions.

Revision ID: 4b8f0c2d91aa
Revises: 0c5a6d91e7f2
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "4b8f0c2d91aa"
down_revision: Union[str, None] = "0c5a6d91e7f2"
branch_labels: Union[str, tuple[str, ...], None] = None
depends_on: Union[str, tuple[str, ...], None] = None


def upgrade() -> None:
    op.add_column("support_threads", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("support_threads", sa.Column("closed_by", sa.String(length=16), nullable=True))
    op.add_column("support_threads", sa.Column("closed_by_name", sa.String(length=128), nullable=True))
    op.add_column("support_threads", sa.Column("close_reason", sa.String(length=32), nullable=True))
    op.create_index("ix_support_threads_closed_at", "support_threads", ["closed_at"], unique=False)

    bind = op.get_bind()

    # Історичні closed-сесії були створені до появи метаданих закриття.
    # Даємо їм час і явну мітку legacy замість порожніх полів у панелі.
    bind.execute(sa.text(
        """
        UPDATE support_threads
        SET closed_at = COALESCE(closed_at, updated_at, last_message_at, created_at),
            closed_by = COALESCE(closed_by, 'system'),
            closed_by_name = COALESCE(closed_by_name, 'Історичне звернення'),
            close_reason = COALESCE(close_reason, 'legacy')
        WHERE status = 'closed'
        """
    ))

    # Попередня версія не мала обмеження «одна відкрита сесія на клієнта».
    # Якщо через гонку в базі вже є дублікати, зберігаємо найновішу open,
    # а старі закриваємо як історичні. Нічого не видаляється.
    rows = bind.execute(sa.text(
        """
        SELECT id, user_id
        FROM support_threads
        WHERE status = 'open'
        ORDER BY user_id, updated_at DESC, id DESC
        """
    )).fetchall()
    seen: set[int] = set()
    duplicates: list[int] = []
    for row in rows:
        user_id = int(row[1])
        if user_id in seen:
            duplicates.append(int(row[0]))
        else:
            seen.add(user_id)

    if duplicates:
        now = bind.execute(sa.select(sa.func.now())).scalar_one()
        for thread_id in duplicates:
            bind.execute(
                sa.text(
                    """
                    UPDATE support_threads
                    SET status = 'closed',
                        closed_at = :closed_at,
                        closed_by = 'system',
                        closed_by_name = 'Міграція життєвого циклу',
                        close_reason = 'deduplicate',
                        updated_at = :closed_at
                    WHERE id = :thread_id AND status = 'open'
                    """
                ),
                {"thread_id": thread_id, "closed_at": now},
            )

    # Фізична гарантія від двох одночасних /ask. Частковий індекс не
    # заважає мати необмежену кількість закритих сесій одного клієнта.
    dialect = bind.dialect.name
    kwargs = {}
    predicate = sa.text("status = 'open'")
    if dialect == "postgresql":
        kwargs["postgresql_where"] = predicate
    elif dialect == "sqlite":
        kwargs["sqlite_where"] = predicate
    else:
        # Продакшен — Postgres. Для невідомого діалекту не створюємо
        # неправильний UNIQUE(user_id), який заборонив би історію сесій.
        return

    op.create_index(
        "uq_support_threads_one_open_per_user",
        "support_threads",
        ["user_id"],
        unique=True,
        **kwargs,
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name in {"postgresql", "sqlite"}:
        op.drop_index("uq_support_threads_one_open_per_user", table_name="support_threads")
    op.drop_index("ix_support_threads_closed_at", table_name="support_threads")
    op.drop_column("support_threads", "close_reason")
    op.drop_column("support_threads", "closed_by_name")
    op.drop_column("support_threads", "closed_by")
    op.drop_column("support_threads", "closed_at")
