from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from shop.config import settings
from shop.models import Base

# У serverless кожен запит — окремий процес, який помирає одразу після відповіді.
# Пул з'єднань там не переживає виклик і лише вичерпує ліміт конектів бази,
# тому вимикаємо його і покладаємось на зовнішній пулер (Neon/Supabase pooler).
_url = settings.db_url
_engine_options: dict = {"echo": False}

if settings.serverless:
    _engine_options["poolclass"] = NullPool
elif _url.startswith("sqlite"):
    # SQLite керує з'єднаннями сам і не приймає параметри розміру пулу
    _engine_options["pool_pre_ping"] = True
else:
    # Числа в налаштуваннях, а не тут: один воркер тримає стільки
    # паралельних запитів до бази, і решта чекає в черзі. Підбирати це
    # значення доводиться під конкретний сервер, а перезбирати образ
    # заради однієї цифри — надто дорого.
    #
    # pool_pre_ping лишається завжди: мертві зʼєднання після нічного
    # простою — класика, і перший ранковий запит падав би з «connection
    # was closed». Пінг коштує мілісекунди, помилка — замовлення.
    _engine_options |= {
        "pool_pre_ping": True,
        "pool_size": settings.db_pool_size,
        "max_overflow": settings.db_pool_overflow,
        # Довгоживучі зʼєднання рвуться мовчки на стороні мережі, і
        # pre_ping їх лише виявляє. Переставляння раз на пів години
        # запобігає самому розриву.
        "pool_recycle": 1800,
        "pool_timeout": 10,
    }

engine = create_async_engine(_url, **_engine_options)
SessionMaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Створює таблиці напряму, без міграцій.

    Тільки для тестів і локального запуску. У продакшені схему накочує
    Alembic: create_all не веде історії версій і при кількох процесах
    перегонить сам себе.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def check_db() -> None:
    """Перевіряє звʼязок із базою і що схема на місці.

    Саме перевірка, а не створення: API стартує кількома воркерами, і будь-яка
    зміна схеми на старті означала б гонку між ними. Порожній результат теж
    успіх — цікавить лише те, що запит дійшов і таблиця існує.
    """
    from sqlalchemy import text

    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
        # Звертаємось до конкретної таблиці: SELECT 1 проходить і на базі
        # без жодної таблиці, а це якраз випадок, коли migrate не відпрацював.
        await conn.execute(text("SELECT COUNT(*) FROM users"))


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionMaker() as session:
        yield session


async def storage_report(limit: int = 12) -> dict:
    """Розмір БД і найбільших таблиць для sysadmin-панелі.

    На PostgreSQL читаємо лише системні каталоги; жодних COUNT(*) по великих
    таблицях. ``n_live_tup``/``n_dead_tup`` — оцінки статистики, зате запит
    дешевий навіть на великій базі. SQLite використовується лише тестами,
    тому там повертаємо короткий unavailable report.
    """
    if _url.startswith("sqlite"):
        return {"available": False, "engine": "sqlite", "tables": []}

    from sqlalchemy import text

    cap = max(1, min(int(limit or 12), 50))
    async with engine.connect() as conn:
        total = int((await conn.execute(text(
            "SELECT pg_database_size(current_database())"
        ))).scalar_one() or 0)
        result = await conn.execute(text(
            """
            SELECT
              s.relname AS name,
              pg_total_relation_size(s.relid) AS total_bytes,
              pg_relation_size(s.relid) AS table_bytes,
              pg_indexes_size(s.relid) AS index_bytes,
              COALESCE(st.n_live_tup, 0) AS live_rows,
              COALESCE(st.n_dead_tup, 0) AS dead_rows
            FROM pg_catalog.pg_statio_user_tables s
            LEFT JOIN pg_catalog.pg_stat_user_tables st ON st.relid = s.relid
            ORDER BY pg_total_relation_size(s.relid) DESC
            LIMIT :limit
            """
        ), {"limit": cap})
        tables = [
            {
                "name": row.name,
                "totalBytes": int(row.total_bytes or 0),
                "tableBytes": int(row.table_bytes or 0),
                "indexBytes": int(row.index_bytes or 0),
                "liveRows": int(row.live_rows or 0),
                "deadRows": int(row.dead_rows or 0),
            }
            for row in result
        ]
        archive_rows = []
        # Після першого deploy міграція вже створює таблицю. Захист через
        # to_regclass лишає endpoint сумісним на короткому проміжку, коли
        # старий API ще працює поруч із новим migrate-контейнером.
        exists = await conn.execute(text("SELECT to_regclass('public.message_archives')"))
        if exists.scalar_one_or_none():
            archive_result = await conn.execute(text(
                """
                SELECT kind, COUNT(*) AS chunks, COALESCE(SUM(message_count), 0) AS messages,
                       COALESCE(SUM(raw_bytes), 0) AS raw_bytes,
                       COALESCE(SUM(octet_length(payload)), 0) AS payload_bytes
                FROM message_archives
                GROUP BY kind
                ORDER BY kind
                """
            ))
            archive_rows = [
                {"kind": row.kind, "chunks": int(row.chunks or 0),
                 "messages": int(row.messages or 0), "rawBytes": int(row.raw_bytes or 0),
                 "payloadBytes": int(row.payload_bytes or 0)}
                for row in archive_result
            ]
    return {"available": True, "engine": "postgresql", "totalBytes": total,
            "tables": tables, "coldArchives": archive_rows}
