"""Тонкий клієнт Bot API — щоб дашборд міг писати клієнтам без запущеного aiogram."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import json

import httpx

from shop.config import settings
from shop.links import canonical_button_url
from shop.services.status_messages import is_permanent_delivery_error

log = logging.getLogger("telegram")
BASE = f"https://api.telegram.org/bot{settings.bot_token}"
_TIMEOUT = httpx.Timeout(15.0)
_MAX_ATTEMPTS = 3


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
    from shop.http_utils import retry_after_seconds
    value = (data.get('parameters') or {}).get('retry_after') if isinstance(data, dict) and isinstance(data.get('parameters') or {}, dict) else None
    return retry_after_seconds(value, default=min(.6 * attempt, 2.0))


async def _call(method: str, payload: dict) -> tuple[bool, str | None]:
    """Retry rejected floods and pre-connect failures, never an ambiguous write."""
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as client:
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                response = await client.post(f'{BASE}/{method}', json=payload)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
                if attempt == _MAX_ATTEMPTS:
                    return False, "З'єднання з Telegram не встановлено"
                await asyncio.sleep(min(.6 * attempt, 2.0))
                continue
            except httpx.HTTPError:
                return False, 'Відповідь Telegram втрачено; доставку не підтверджено'
            try:
                data = response.json()
            except ValueError:
                return False, 'Telegram повернув нечитабельну відповідь; доставку не підтверджено'
            if not isinstance(data, dict):
                return False, 'Telegram повернув некоректну відповідь; доставку не підтверджено'
            if data.get('ok') is True:
                return True, None
            error = str(data.get('description') or f'HTTP {response.status_code}')[:500]
            if settings.bot_token:
                error = error.replace(settings.bot_token, '[redacted]')
            try:
                code = int(data.get('error_code') or response.status_code)
            except (ValueError, TypeError):
                code = response.status_code
            if code == 429:
                delay = _retry_after(data, attempt)
                # Long waits belong to durable jobs, not an open checkout HTTP request.
                if delay > 2 or attempt == _MAX_ATTEMPTS:
                    return False, f'Telegram обмежив частоту запитів; пауза {delay:g} с'
                await asyncio.sleep(delay)
                continue
            return False, error
    return False, 'Telegram не підтвердив доставку'


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
    from shop.services.broadcast_content import local_media_name
    if photo_url and local_media_name(photo_url):
        result = await send_broadcast_once(tg_id, text, photo_url, button_text, button_url)
        return result.status == 'sent', result.error
    payload: dict = {"chat_id": tg_id, "parse_mode": "HTML"}

    if button_text and button_url:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": button_text, "url": canonical_button_url(button_url)}]]
        }

    if photo_url:
        payload |= {"photo": photo_url, "caption": text}
        return await _call("sendPhoto", payload)

    payload["text"] = text
    return await _call("sendMessage", payload)


@dataclass(frozen=True)
class BroadcastDeliveryResult:
    status: str  # sent / failed / retry / unknown
    error: str | None = None
    retry_after: float = 1.0


async def send_broadcast_once(tg_id: int, text: str, photo_url: str | None = None,
                              button_text: str | None = None,
                              button_url: str | None = None, *, text_format: str = 'html',
                              client: httpx.AsyncClient | None = None) -> BroadcastDeliveryResult:
    """One durable queue attempt; never repeat an ambiguous network outcome.

    The recipient journal owns retries and the shared client reuses connections.
    """
    from shop.services.broadcast_content import validate_content
    from shop.services.broadcast_media import telegram_photo
    from starlette.concurrency import run_in_threadpool
    try:
        validate_content(text, photo_url, text_format, button_text, button_url)
        photo = await run_in_threadpool(telegram_photo, photo_url) if photo_url else None
    except (ValueError, OSError):
        return BroadcastDeliveryResult('failed', 'Перевірте текст і зображення розсилки; файл недоступний або вміст некоректний')
    payload: dict = {"chat_id": tg_id}
    if text_format == 'html':
        payload['parse_mode'] = 'HTML'
    if button_text and button_url:
        payload["reply_markup"] = {"inline_keyboard": [[{
            "text": button_text, "url": canonical_button_url(button_url)}]]}
    method = "sendPhoto" if photo_url else "sendMessage"
    payload.update({"photo": photo_url, "caption": text} if photo_url else {"text": text})
    try:
        async def post(connection):
            if photo is not None:
                payload.pop('photo', None)
                fields = {key: json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else str(value)
                          for key, value in payload.items()}
                return await connection.post(f"{BASE}/{method}", data=fields,
                    files={'photo': ('broadcast.jpg', photo, 'image/jpeg')})
            return await connection.post(f"{BASE}/{method}", json=payload)
        if client is not None:
            response = await post(client)
        else:
            async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False) as owned_client:
                response = await post(owned_client)
        try:
            data = response.json()
        except ValueError:
            return BroadcastDeliveryResult("unknown", "Telegram повернув нечитабельну відповідь")
        if not isinstance(data, dict):
            return BroadcastDeliveryResult("unknown", "Некоректна відповідь Telegram")
        if data.get("ok") is True:
            return BroadcastDeliveryResult("sent")
        error = str(data.get("description") or f"HTTP {response.status_code}")[:500]
        if settings.bot_token:
            error = error.replace(settings.bot_token, '[redacted]')
        try:
            code = int(data.get("error_code") or response.status_code)
        except (TypeError, ValueError):
            code = response.status_code
        if code == 429:
            delay = max(1.0, _retry_after(data, 1))
            return BroadcastDeliveryResult("retry", error, delay)
        if isinstance(code, int) and 400 <= code < 500:
            return BroadcastDeliveryResult("failed", error)
        # A gateway/server failure may occur after Telegram accepts the request.
        return BroadcastDeliveryResult("unknown", error)
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        return BroadcastDeliveryResult("retry", "З'єднання з Telegram не встановлено", 5.0)
    except httpx.HTTPError:
        # Avoid leaking token-bearing request URLs into persisted error text.
        return BroadcastDeliveryResult("unknown", "Відповідь Telegram втрачено; доставку не підтверджено")
