"""Легка внутрішня шина live-подій ELFAR.

Статуси замовлень змінюються з кількох процесів: API приймає webhook
SalesDrive, bot виконує дії менеджера/покупця, scheduler страхує CRM read-side.
Оновлювати браузер лише polling-ом означає гарантовану затримку. Redis уже є
частиною production stack, тому використовуємо його як pub/sub без нового ENV.

Подія НЕ є джерелом даних і не містить приватних деталей замовлення. Вона лише
каже клієнту «замовлення N змінилось»; браузер після цього читає канонічний API.
Якщо Redis тимчасово недоступний, бізнес-операція не блокується, а звичайний
fallback polling наздожене стан.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from urllib.parse import quote

from shop.config import settings

log = logging.getLogger(__name__)

CHANNEL = "elfar:orders:realtime:v1"
HEARTBEAT_SECONDS = 15.0

# In-process fallback для локального запуску без Redis. У production основний
# канал Redis, бо API/bot/scheduler живуть у різних контейнерах.
_local_subscribers: set[asyncio.Queue] = set()


def _redis_url() -> str:
    configured = str(getattr(settings, "redis_url", "") or "").strip()
    if configured:
        return configured
    # Production compose уже має REDIS_PASSWORD. Якщо REDIS_URL випадково
    # прибрали зі старого .env, live-sync не повинен мовчки вимикатися.
    password = str(getattr(settings, "redis_password", "") or "").strip()
    if password and not getattr(settings, "serverless", False):
        return f"redis://:{quote(password, safe='')}@redis:6379/0"
    return ""


def _event(kind: str, order_id: int, user_id: int | None, fields) -> dict:
    return {
        "eventId": uuid.uuid4().hex,
        "kind": kind,
        "orderId": int(order_id),
        "userId": int(user_id) if user_id else None,
        "fields": sorted({str(x) for x in (fields or []) if str(x)}),
        "at": time.time(),
    }


async def _publish_local(payload: dict) -> None:
    stale = []
    for queue in tuple(_local_subscribers):
        try:
            if queue.full():
                # Live-події інвалідовують кеш, тому достатньо лишити
                # найсвіжіші. Не дозволяємо повільній вкладці рости без меж.
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(payload)
        except Exception:
            stale.append(queue)
    for queue in stale:
        _local_subscribers.discard(queue)


async def publish_order_changed(
    order_id: int,
    *,
    user_id: int | None = None,
    fields=(),
    created: bool = False,
) -> None:
    """Best-effort подія після успішного COMMIT замовлення."""
    payload = _event("order.created" if created else "order.changed", order_id, user_id, fields)
    url = _redis_url()
    if not url:
        await _publish_local(payload)
        return

    try:
        import redis.asyncio as redis

        client = redis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=0.4,
            socket_timeout=0.6,
            health_check_interval=30,
        )
        try:
            await client.publish(CHANNEL, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        finally:
            await client.aclose()
    except Exception as exc:
        # Redis не має права затримати/зірвати зміну статусу. У процесі API
        # local fallback усе одно дасть live-update вкладкам цього інстансу.
        await _publish_local(payload)
        log.warning(
            "Live-подію замовлення %s не вдалося відправити через Redis: %s",
            order_id,
            exc,
            extra={"event": "realtime.publish.failed", "orderId": order_id},
        )


def emit_order_changed(
    order_id: int,
    *,
    user_id: int | None = None,
    fields=(),
    created: bool = False,
) -> None:
    """Не блокує бізнес-транзакцію очікуванням pub/sub."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    task = loop.create_task(
        publish_order_changed(order_id, user_id=user_id, fields=fields, created=created)
    )

    def _done(future: asyncio.Task) -> None:
        try:
            future.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            log.exception(
                "Необроблена помилка live-події замовлення %s",
                order_id,
                extra={"event": "realtime.publish.crashed", "orderId": order_id},
            )

    task.add_done_callback(_done)


async def _local_events() -> AsyncIterator[dict | None]:
    queue: asyncio.Queue = asyncio.Queue(maxsize=128)
    _local_subscribers.add(queue)
    try:
        while True:
            try:
                yield await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
            except asyncio.TimeoutError:
                yield None
    finally:
        _local_subscribers.discard(queue)


async def subscribe_order_events() -> AsyncIterator[dict | None]:
    """Події Redis; ``None`` — heartbeat. При недоступному Redis local fallback."""
    url = _redis_url()
    if not url:
        async for item in _local_events():
            yield item
        return

    try:
        import redis.asyncio as redis

        client = redis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=None,
            health_check_interval=30,
        )
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(CHANNEL)
        try:
            while True:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=HEARTBEAT_SECONDS,
                )
                if not message:
                    yield None
                    continue
                raw = message.get("data")
                if not isinstance(raw, str):
                    continue
                try:
                    payload = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(payload, dict) and payload.get("orderId"):
                    yield payload
        finally:
            try:
                await pubsub.unsubscribe(CHANNEL)
            finally:
                await pubsub.aclose()
                await client.aclose()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        log.warning(
            "Redis live-stream недоступний, використовую local fallback: %s",
            exc,
            extra={"event": "realtime.subscribe.fallback"},
        )
        async for item in _local_events():
            yield item
