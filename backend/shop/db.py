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
