"""Привітання для груп і каналів.

Винесено окремо, бо потрібне у двох місцях: у PrivateOnlyMiddleware (коли
бота покликали повідомленням) і в обробнику my_chat_member (коли бота щойно
додали). Мідлвар працює до роутерів, тож поділитися кодом через роутер не
вийшло б.
"""
from __future__ import annotations

import logging

from bot import keyboards as kb
from bot import texts
from shop.config import settings
from shop.services.shop_settings import current
from shop.repo.factory import open_repo
from shop.services.shop_settings import get_shop_settings

log = logging.getLogger(__name__)

# Команди, на які бот відгукується в групі. Список навмисно короткий:
# усе інше в публічному чаті ігнорується, щоб не було ні спаму, ні витоку.
GREETING_COMMANDS = ("/start", "/shop", "/magazin")


def is_greeting_trigger(text: str | None) -> bool:
    """Чи варто відповідати на це повідомлення в групі."""
    if not text:
        return False
    lowered = text.strip().lower()

    for command in GREETING_COMMANDS:
        # враховуємо форму /start@bot_name
        if lowered == command or lowered.startswith(command + " ") or lowered.startswith(command + "@"):
            return True

    username = (current().bot_username or "").lstrip("@").lower()
    return bool(username) and f"@{username}" in lowered


async def shop_name() -> str:
    """Назва магазину з налаштувань, із відкотом на .env при збої бази."""
    try:
        async with open_repo() as repo:
            return (await get_shop_settings(repo)).shop_name
    except Exception:
        log.warning("Не вдалося прочитати налаштування для привітання", exc_info=True)
        return settings.shop_name


async def send_greeting(target) -> None:
    """Надсилає привітання з кнопкою переходу в приватний чат."""
    markup = kb.to_private_chat()
    if not markup.inline_keyboard:
        log.warning("BOT_USERNAME не заданий — кнопку переходу побудувати нічим")
        return
    try:
        await target.answer(texts.GROUP_GREETING.format(shop=await shop_name()), reply_markup=markup)
    except Exception:
        # У каналі бот може не мати права писати, у групі — бути обмеженим.
        # Це очікувана ситуація, а не збій застосунку.
        log.info("Не вдалося надіслати привітання в публічний чат", exc_info=True)
