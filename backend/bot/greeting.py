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

# Єдина команда, на яку бот відгукується в групі чи каналі.
#
# /start тут навмисно немає. У Telegram кожен новий учасник рано чи пізно
# надсилає /start у групу за звичкою, і бот відповідав би привітанням на
# кожен такий випадок — це і є той спам, якого не має бути. У приватному
# чаті /start працює як завжди: там він адресований саме боту.
PUBLIC_COMMANDS = ("/shop",)

# Команди, які лишаються приватними. Перелік потрібен, щоб у групі мовчати
# свідомо, а не через те, що команда невідома.
PRIVATE_ONLY_COMMANDS = ("/start", "/magazin", "/cart", "/profile", "/orders")


def _matches(text: str, commands: tuple[str, ...]) -> bool:
    """Чи є текст однією з команд, із урахуванням форми /shop@bot_name."""
    lowered = text.strip().lower()
    for command in commands:
        if lowered == command or lowered.startswith(command + " ") or lowered.startswith(command + "@"):
            return True
    return False


def is_command_trigger(text: str | None) -> bool:
    """Публічна команда, на яку відповідаємо в групі."""
    if not text:
        return False
    return _matches(text, PUBLIC_COMMANDS)


def is_private_only_command(text: str | None) -> bool:
    """Приватна команда, надіслана не туди. Причина мовчання, а не незнання."""
    if not text:
        return False
    return _matches(text, PRIVATE_ONLY_COMMANDS)


def is_greeting_trigger(text: str | None) -> bool:
    """Чи варто відповідати на це повідомлення в групі."""
    if not text:
        return False
    lowered = text.strip().lower()

    if _matches(lowered, PUBLIC_COMMANDS):
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
