"""Тонкий клієнт Bot API — щоб дашборд міг писати клієнтам без запущеного aiogram."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging

import httpx

from shop.config import settings
from shop.services.status_messages import is_permanent_delivery_error

log = logging.getLogger("telegram")
BASE = f"https://api.telegram.org/bot{settings.bot_token}"
_TIMEOUT = httpx.Timeout(15.0)
_MAX_ATTEMPTS = 3
_RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass(frozen=True)
class DeliveryResult:
    """Результат доставки приватного повідомлення клієнту.

    ``permanent`` відрізняє «користувач не відкрив/заблокував бота» від
    429/502/timeout. Тимчасова аварія Telegram не повинна змінювати
    ``bot_reachable``.
    """

    delivered: bool
    error: str | None = None
    permanent: bool = False


def _retry_after(data: object, attempt: int) -> float:
    """Пауза перед повтором Bot API з повагою до Telegram retry_after."""
    if isinstance(data, dict):
        try:
            seconds = float((data.get("parameters") or {}).get("retry_after") or 0)
            if seconds > 0:
                return min(seconds, 10.0)
        except (TypeError, ValueError):
            pass
    return min(0.6 * attempt, 2.0)


async def _call(method: str, payload: dict) -> tuple[bool, str | None]:
    """Викликає Bot API з коротким retry лише для тимчасових збоїв.

    400/403 та інші постійні помилки не повторюємо. Це принципово для
    ``chat not found``: повтор без дії користувача нічого не змінює. Натомість
    429/5xx/timeout із наданих логів — тимчасові й отримують до двох повторів.
    """
    last_error: str | None = None
    attempts_made = 0

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            attempts_made = attempt
            data: object = None
            status_code: int | None = None
            try:
                response = await client.post(f"{BASE}/{method}", json=payload)
                status_code = response.status_code
                try:
                    data = response.json()
                except ValueError:
                    data = None

                if isinstance(data, dict) and data.get("ok"):
                    return True, None

                if isinstance(data, dict):
                    last_error = str(data.get("description") or f"HTTP {status_code}")
                else:
                    last_error = f"HTTP {status_code}"

                retryable = status_code in _RETRYABLE_STATUS or (
                    status_code is not None and status_code >= 500
                )
                if not retryable or attempt >= _MAX_ATTEMPTS:
                    break

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = str(exc) or exc.__class__.__name__
                if attempt >= _MAX_ATTEMPTS:
                    break
            except Exception as exc:  # непередбачений локальний збій
                log.warning("Bot API %s failed: %s", method, exc)
                return False, str(exc)

            delay = _retry_after(data, attempt)
            log.warning(
                "Bot API %s тимчасово недоступний, повтор %s/%s за %.1f с: %s",
                method, attempt + 1, _MAX_ATTEMPTS, delay, last_error,
                extra={"event": "telegram.api.retry", "method": method,
                       "attempt": attempt, "status": status_code},
            )
            await asyncio.sleep(delay)

    if last_error:
        log.warning(
            "Bot API %s не виконав запит після %s спроб: %s",
            method, attempts_made, last_error,
            extra={"event": "telegram.api.failed", "method": method},
        )
    return False, last_error


async def notify_user(tg_id: int, text: str) -> bool:
    return (await notify_user_detailed(tg_id, text)).delivered


async def notify_user_detailed(tg_id: int, text: str) -> DeliveryResult:
    """Надсилає повідомлення й не втрачає причину невдачі."""
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
