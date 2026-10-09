from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Request, HTTPException
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
async def order_events(request: Request, _who: Principal = Depends(require_staff)):
    """Авторизований live-stream інвалідації замовлень для панелі.

    Стрім навмисно закривається раз на 5 хвилин: reconnect повторно проходить
    require_staff, тому вимкнений менеджер не тримає старе з'єднання до кінця
    JWT. Дані замовлення через SSE не віддаються — лише id/тип зміни.
    """
    async def generate():
        started = time.monotonic()
        yield "retry: 1500\nevent: ready\ndata: {}\n\n"
        async for payload in subscribe_order_events():
            # Re-check credentials on each event/heartbeat using a fresh DB session.
            # Logout and password/role changes close an already open stream too.
            from shop.repo.factory import get_repo
            from api.auth import _request_principal, security
            dependency = request.app.dependency_overrides.get(get_repo, get_repo)
            generator = dependency()
            try:
                repo = await generator.__anext__()
                await _request_principal(request, await security(request), repo)
            except HTTPException:
                yield "event: session-ended\ndata: {}\n\n"
                break
            finally:
                await generator.aclose()
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
