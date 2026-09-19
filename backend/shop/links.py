"""Побудова публічних посилань на бота та магазин.

Основний вхід у Mini App — Named Mini App Telegram. Це важливо не лише для
зручності: Telegram сам створює коректний WebApp-контекст і передає initData.
Прямі URL виду ``https://site/app/`` лишаються внутрішньою адресою вебзастосунку
для MenuButtonWebApp, але не використовуються у звичайних inline-кнопках.
"""
from __future__ import annotations

from urllib.parse import quote

from shop.services.shop_settings import current


# Канонічний Named Mini App магазину. Його коротка назва керується BotFather,
# а не нашим сайтом, тому URL фіксуємо явно: кнопки не повинні залежати від
# випадково застарілого PUBLIC_URL або значення в БД.
NAMED_MINIAPP_URL = "https://t.me/elfarshop_bot/elfar"


def bot_name() -> str:
    """Юзернейм бота без «собаки». Порожній рядок, якщо не заданий."""
    return (current().bot_username or "").lstrip("@").strip("/")


def app_link(start_param: str | None = None) -> str:
    """Канонічне посилання на Named Mini App.

    ``startapp`` передається Telegram усередині підписаного launch context і
    доступний як ``initDataUnsafe.start_param``. Так реферальні посилання та
    кнопки чату відкривають саме Mini App, не втрачаючи авторизацію Telegram.
    """
    if not start_param:
        return NAMED_MINIAPP_URL
    payload = quote(str(start_param).strip(), safe="-_")
    return f"{NAMED_MINIAPP_URL}?startapp={payload}" if payload else NAMED_MINIAPP_URL


def chat_link(start_param: str | None = None) -> str:
    """Посилання саме в особистий чат із ботом, повз вітрину.

    Цей шлях потрібен, коли користувач ще не починав чат або заблокував бота:
    відкриття Mini App саме по собі не дає боту права ініціювати діалог.
    """
    name = bot_name()
    if not name:
        return ""
    if start_param:
        payload = quote(str(start_param).strip(), safe="-_")
        return f"https://t.me/{name}?start={payload}" if payload else f"https://t.me/{name}"
    return f"https://t.me/{name}"


def share_link(url: str, text: str = "Раджу цей магазин") -> str:
    """Нативний діалог «поділитися» Telegram."""
    return f"https://t.me/share/url?url={quote(url, safe='')}&text={quote(text)}"
