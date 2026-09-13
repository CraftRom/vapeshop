"""Побудова публічних посилань на бота та магазин.

Кнопки WebApp усередині Telegram будуються окремо з актуального PUBLIC_URL.
Публічні/реферальні URL навмисно ведуть спочатку в чат із ботом: адреса
Named Mini App зберігається в BotFather поза нашою БД і може лишитися старою
після зміни домену. Так ми не даємо зовнішньому застарілому URL ламати вхід.
"""
from __future__ import annotations

from shop.services.shop_settings import current


def bot_name() -> str:
    """Юзернейм бота без «собаки». Порожній рядок, якщо не заданий."""
    return (current().bot_username or "").lstrip("@")


def app_link(start_param: str | None = None) -> str:
    """Надійне публічне посилання на магазин через чат із ботом.

    Історично тут використовувався ``t.me/<bot>/<miniapp>?startapp=...``.
    Адреса такого Named Mini App зберігається у BotFather окремо від нашої
    БД, тож після переїзду з ``www`` вона могла лишитися застарілою і
    Telegram відкривав host, який не існує. Deep link ``?start=`` не містить
    URL сайту взагалі: бот відкривається гарантовано, а вже його WebApp-кнопка
    будується з актуального канонічного PUBLIC_URL.

    Назву функції лишаємо для сумісності з API/профілем.
    """
    return chat_link(start_param)


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
