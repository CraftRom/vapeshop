"""Запуск бота в режимі polling — для власного сервера."""
from __future__ import annotations

import asyncio
import logging

from bot.factory import build_bot, build_dispatcher
from shop.db import init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
log = logging.getLogger("bot")


async def main() -> None:
    await init_db()

    bot = build_bot()
    dp = build_dispatcher()

    me = await bot.get_me()
    log.info("Бот @%s запущено в режимі polling", me.username)

    # Знімаємо вебхук: інакше Telegram не віддасть апдейти через polling
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        log.info("Зупинено")
