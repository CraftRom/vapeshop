from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from api.auth import Principal, require_staff
from shop.services.realtime import subscribe_order_events

router = APIRouter()
STREAM_MAX_SECONDS = 5 * 60


def _frame(payload: dict) -> str:
    return (
        f"id: {payload.get('eventId', '')}\n"
        f"event: order\n"
        f"data: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


@router.get("/orders")
async def order_events(_who: Principal = Depends(require_staff)):
    """Авторизований live-stream інвалідації замовлень для панелі.

    Стрім навмисно закривається раз на 5 хвилин: reconnect повторно проходить
    require_staff, тому вимкнений менеджер не тримає старе з'єднання до кінця
    JWT. Дані замовлення через SSE не віддаються — лише id/тип зміни.
    """
    async def generate():
        started = time.monotonic()
        yield "retry: 1500\nevent: ready\ndata: {}\n\n"
        async for payload in subscribe_order_events():
            if time.monotonic() - started >= STREAM_MAX_SECONDS:
                yield "event: reconnect\ndata: {}\n\n"
                break
            if payload is None:
                yield ": heartbeat\n\n"
                continue
            yield _frame(payload)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
