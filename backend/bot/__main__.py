"""Запуск бота в режимі polling — для власного сервера."""
from __future__ import annotations

import asyncio
import logging

from aiogram.utils.backoff import BackoffConfig
from aiogram.types import BotCommand

from shop.logging_setup import setup as setup_logging

from bot.factory import build_bot, build_dispatcher
from bot.version import BOT_VERSION
from shop.db import init_db

setup_logging("bot")
log = logging.getLogger("bot")


async def main() -> None:
    log.info("Бот %s запускається", BOT_VERSION,
             extra={"event": "bot.start", "version": BOT_VERSION})
    await init_db()

    bot = build_bot()
    dp = build_dispatcher()

    me = await bot.get_me()
    await bot.set_my_commands([
        BotCommand(command="shop", description="Відкрити магазин"),
        BotCommand(command="orders", description="Мої замовлення"),
        BotCommand(command="ask", description="Написати менеджеру / техпідтримці"),
        BotCommand(command="done", description="Завершити звернення"),
        BotCommand(command="help", description="Довідка"),
    ])
    log.info("Бот @%s запущено в режимі polling", me.username)

    # Знімаємо вебхук: інакше Telegram не віддасть апдейти через polling.
    # pending updates НЕ стираємо. У журналі багато коректних SIGTERM під
    # час деплоїв; із drop_pending_updates=True кожен такий рестарт міг
    # мовчки викинути повідомлення, що прийшли між stop і наступним start.
    await bot.delete_webhook(drop_pending_updates=False)

    # 2026-09-09 Telegram повернув Flood control (retry after 5), а стандартний
    # backoff aiogram почав нові GetUpdates уже через ~1 c і потім отримав
    # серію 502. Мінімальна пауза 5 секунд не «лікує» сервер Telegram, але
    # не добиває його повторними запитами раніше за вказане в логах вікно.
    # Довший long-poll одночасно зменшує частоту GetUpdates у спокої.
    polling_backoff = BackoffConfig(
        min_delay=5.0,
        max_delay=30.0,
        factor=1.7,
        jitter=1.0,
    )
    await dp.start_polling(
        bot,
        polling_timeout=30,
        backoff_config=polling_backoff,
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Зупинено")
