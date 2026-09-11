"""Тонкий клієнт Bot API — щоб дашборд міг писати клієнтам без запущеного aiogram."""
from __future__ import annotations

from dataclasses import dataclass
import logging

import httpx

from shop.config import settings
from shop.services.status_messages import is_permanent_delivery_error

log = logging.getLogger("telegram")
BASE = f"https://api.telegram.org/bot{settings.bot_token}"


@dataclass(frozen=True)
class DeliveryResult:
    """Результат доставки приватного повідомлення клієнту.

    ``permanent`` відрізняє «користувач не відкрив/заблокував бота» від
    429/502/timeout. Раніше обидва випадки зводились до ``False`` і панель
    записувала ``bot_reachable=False`` навіть після короткого мережевого
    збою Telegram.
    """

    delivered: bool
    error: str | None = None
    permanent: bool = False


async def _call(method: str, payload: dict) -> tuple[bool, str | None]:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(f"{BASE}/{method}", json=payload)
            data = response.json()
            if data.get("ok"):
                return True, None
            return False, data.get("description")
    except Exception as exc:  # мережа впала — не валимо весь запит
        log.warning("Bot API %s failed: %s", method, exc)
        return False, str(exc)


async def notify_user(tg_id: int, text: str) -> bool:
    return (await notify_user_detailed(tg_id, text)).delivered


async def notify_user_detailed(tg_id: int, text: str) -> DeliveryResult:
    """Надсилає повідомлення й не втрачає причину невдачі.

    Сумісний ``notify_user`` лишається для місць, яким потрібен тільки bool,
    а статуси замовлень використовують цей варіант, щоб не плутати
    недоступний чат із тимчасовою аварією Telegram.
    """
    ok, error = await _call(
        "sendMessage", {"chat_id": tg_id, "text": text, "parse_mode": "HTML"}
    )
    return DeliveryResult(
        delivered=ok,
        error=error,
        permanent=(not ok and is_permanent_delivery_error(error or "")),
    )


async def send_broadcast_message(
    tg_id: int,
    text: str,
    photo_url: str | None = None,
    button_text: str | None = None,
    button_url: str | None = None,
) -> tuple[bool, str | None]:
    payload: dict = {"chat_id": tg_id, "parse_mode": "HTML"}

    if button_text and button_url:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": button_text, "url": button_url}]]
        }

    if photo_url:
        payload |= {"photo": photo_url, "caption": text}
        return await _call("sendPhoto", payload)

    payload["text"] = text
    return await _call("sendMessage", payload)
