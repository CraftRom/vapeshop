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
    _engine_options |= {"pool_pre_ping": True, "pool_size": 10, "max_overflow": 20}

engine = create_async_engine(_url, **_engine_options)
SessionMaker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Створює таблиці. Для продакшену використовуйте Alembic — див. docs/SERVER.md."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionMaker() as session:
        yield session
