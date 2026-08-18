from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin
from api.schemas import BroadcastIn, BroadcastOut, SegmentIn
from shop.db import SessionMaker, get_session
from shop.models import Broadcast, BroadcastStatus
from shop.services import segments as segment_service
from shop.telegram import send_broadcast_message

router = APIRouter(dependencies=[Depends(require_admin)])
log = logging.getLogger("broadcast")

RATE_LIMIT = 25  # повідомлень за секунду; Telegram дозволяє ~30


@router.get("/segments")
async def available_segments():
    return [{"type": key, "label": label} for key, label in segment_service.SEGMENTS.items()]


@router.post("/preview")
async def preview_segment(segment: SegmentIn, session: AsyncSession = Depends(get_session)):
    count = await segment_service.count(session, segment.model_dump(exclude_none=True))
    return {"count": count}


@router.get("", response_model=list[BroadcastOut])
async def list_broadcasts(session: AsyncSession = Depends(get_session)):
    return list(await session.scalars(select(Broadcast).order_by(Broadcast.created_at.desc())))


@router.post("", response_model=BroadcastOut, status_code=201)
async def create_broadcast(data: BroadcastIn, session: AsyncSession = Depends(get_session)):
    broadcast = Broadcast(
        **data.model_dump(exclude={"segment"}),
        segment=data.segment.model_dump(exclude_none=True),
    )
    session.add(broadcast)
    await session.commit()
    await session.refresh(broadcast)
    return broadcast


@router.post("/{broadcast_id}/send", response_model=BroadcastOut)
async def send_broadcast(
    broadcast_id: int,
    background: BackgroundTasks,
    session: AsyncSession = Depends(get_session),
):
    broadcast = await session.get(Broadcast, broadcast_id)
    if not broadcast:
        raise HTTPException(404, "Розсилку не знайдено")
    if broadcast.status == BroadcastStatus.SENDING:
        raise HTTPException(409, "Розсилка вже виконується")
    if broadcast.status == BroadcastStatus.SENT:
        raise HTTPException(409, "Цю розсилку вже надіслано")

    broadcast.status = BroadcastStatus.SENDING
    broadcast.sent_count = 0
    broadcast.failed_count = 0
    await session.commit()
    await session.refresh(broadcast)

    background.add_task(_run_broadcast, broadcast_id)
    return broadcast


async def _run_broadcast(broadcast_id: int) -> None:
    async with SessionMaker() as session:
        broadcast = await session.get(Broadcast, broadcast_id)
        if not broadcast:
            return

        recipients = await segment_service.tg_ids(session, broadcast.segment or {})
        sent = failed = 0

        for index, tg_id in enumerate(recipients, start=1):
            ok, error = await send_broadcast_message(
                tg_id,
                broadcast.text,
                broadcast.photo_url,
                broadcast.button_text,
                broadcast.button_url,
            )
            if ok:
                sent += 1
            else:
                failed += 1
                log.info("Не доставлено %s: %s", tg_id, error)

            if index % RATE_LIMIT == 0:
                broadcast.sent_count, broadcast.failed_count = sent, failed
                await session.commit()
                await asyncio.sleep(1)

        broadcast.sent_count = sent
        broadcast.failed_count = failed
        broadcast.status = BroadcastStatus.SENT
        broadcast.finished_at = datetime.now(timezone.utc)
        await session.commit()
        log.info("Розсилка %s завершена: %s доставлено, %s помилок", broadcast_id, sent, failed)


@router.delete("/{broadcast_id}", status_code=204)
async def delete_broadcast(broadcast_id: int, session: AsyncSession = Depends(get_session)):
    broadcast = await session.get(Broadcast, broadcast_id)
    if not broadcast:
        raise HTTPException(404, "Розсилку не знайдено")
    if broadcast.status == BroadcastStatus.SENDING:
        raise HTTPException(409, "Не можна видалити розсилку, яка виконується")
    await session.delete(broadcast)
    await session.commit()
