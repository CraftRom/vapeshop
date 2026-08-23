"""Спільна збірка бота для обох режимів.

Polling (`python -m bot`) і webhook (serverless) мають отримувати однаковий
набір роутерів і middleware — інакше поведінка почне розходитись залежно від
того, де розгорнуто проєкт.
"""
from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from shop.config import settings

log = logging.getLogger("bot.factory")


def build_bot() -> Bot:
    return Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )


def build_storage():
    """Redis, якщо заданий — інакше стан оформлення губиться при рестарті."""
    if settings.redis_url:
        try:
            from aiogram.fsm.storage.redis import RedisStorage

            return RedisStorage.from_url(settings.redis_url)
        except ImportError:
            log.warning("REDIS_URL заданий, але пакет redis не встановлено — беремо пам'ять")
    elif settings.serverless:
        # У serverless пам'ять не переживає навіть сусідній запит:
        # кожне повідомлення може потрапити в новий процес.
        log.warning(
            "Serverless без REDIS_URL: багатокрокове оформлення замовлення працюватиме "
            "нестабільно. Підключіть Upstash Redis."
        )
    return MemoryStorage()


def build_dispatcher() -> Dispatcher:
    from bot.handlers import (
        admin, cart, catalog, chat, checkout, group, profile, start,
    )
    from bot.middlewares import (
        AgeGateMiddleware, BlockedUserMiddleware, PrivateOnlyMiddleware,
        RepositoryMiddleware,
    )

    dp = Dispatcher(storage=build_storage())

    for observer in (dp.message, dp.callback_query):
        # PrivateOnlyMiddleware — найпершим: у публічному чаті апдейт не має
        # доходити ні до бази, ні до хендлерів
        observer.middleware(PrivateOnlyMiddleware())
        observer.middleware(RepositoryMiddleware())
        observer.middleware(BlockedUserMiddleware())
        observer.middleware(AgeGateMiddleware())

    dp.include_router(group.router)      # групи й канали — окремо від магазину
    dp.include_router(admin.router)      # адмінський роутер — першим
    dp.include_router(start.router)
    dp.include_router(catalog.router)
    dp.include_router(cart.router)
    dp.include_router(checkout.router)
    dp.include_router(profile.router)
    # Чат із оператором — останнім: ловить лише те, що не розібрали інші
    dp.include_router(chat.router)

    return dp


def webhook_path() -> str:
    """Секрет у шляху — щоб сторонні не могли слати боту фейкові апдейти."""
    secret = settings.webhook_secret or "hook"
    return f"/api/telegram/{secret}"
