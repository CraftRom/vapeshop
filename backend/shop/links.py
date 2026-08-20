"""Побудова посилань на бота й на вітрину.

Зібрано в одному місці, бо формат залежить від того, чи зареєстровано
Mini App у BotFather, і різні частини коду не мають вирішувати це кожна
по-своєму.

Зареєстрований застосунок має власну коротку назву, і пряме посилання
виглядає як t.me/<бот>/<назва>. Саме на нього треба вішати ?startapp=,
інакше параметр до вітрини не дійде.
"""
from __future__ import annotations

from shop.services.shop_settings import current


def bot_name() -> str:
    """Юзернейм бота без «собаки». Порожній рядок, якщо не заданий."""
    return (current().bot_username or "").lstrip("@")


def app_link(start_param: str | None = None) -> str:
    """Пряме посилання на вітрину.

    Без зареєстрованого застосунку відкотимось на посилання в чат із ботом:
    вітрина тоді доступна кнопкою в меню, а не за прямим посиланням.
    """
    name = bot_name()
    if not name:
        return ""

    short = (current().miniapp_short_name or "").strip().lstrip("/")
    base = f"https://t.me/{name}/{short}" if short else f"https://t.me/{name}"

    if not start_param:
        return base

    # startapp розуміє вітрина, start — чат із ботом
    key = "startapp" if short else "start"
    return f"{base}?{key}={start_param}"


def chat_link(start_param: str | None = None) -> str:
    """Посилання саме в особистий чат із ботом, повз вітрину."""
    name = bot_name()
    if not name:
        return ""
    return f"https://t.me/{name}?start={start_param}" if start_param else f"https://t.me/{name}"


def share_link(url: str, text: str = "Раджу цей магазин") -> str:
    """Нативний діалог «поділитися» Telegram."""
    from urllib.parse import quote

    return f"https://t.me/share/url?url={quote(url, safe='')}&text={quote(text)}"
