from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.auth import require_staff
from api.schemas import BroadcastIn, BroadcastOut, SegmentIn
from shop.config import settings
from shop.entities import BroadcastStatus
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services import broadcast as broadcast_service

router = APIRouter(dependencies=[Depends(require_staff)])
log = logging.getLogger("broadcast")

SEGMENTS = {
    "all": "Усі клієнти",
    "with_orders": "З покупками",
    "no_orders": "Без покупок",
    "inactive": "Не заходили N днів",
    "top_spenders": "Витратили більше N грн",
    "with_referrals": "Привели друзів",
}


@router.get("/segments")
async def available_segments():
    return [{"type": key, "label": label} for key, label in SEGMENTS.items()]


@router.post("/preview")
async def preview_segment(segment: SegmentIn, repo: Repository = Depends(get_repo)):
    return {"count": await repo.count_segment(segment.model_dump(exclude_none=True))}


@router.get("", response_model=list[BroadcastOut])
async def list_broadcasts(repo: Repository = Depends(get_repo)):
    return await repo.list_broadcasts()


@router.post("", response_model=BroadcastOut, status_code=201)
async def create_broadcast(data: BroadcastIn, repo: Repository = Depends(get_repo)):
    payload = data.model_dump(exclude={"segment"})
    payload["segment"] = data.segment.model_dump(exclude_none=True)
    return await repo.create_broadcast(payload)


@router.post("/{broadcast_id}/send", response_model=BroadcastOut)
async def send_broadcast(
    broadcast_id: int,
    background: BackgroundTasks,
    repo: Repository = Depends(get_repo),
):
    broadcast = await repo.get_broadcast(broadcast_id)
    if not broadcast:
        raise HTTPException(404, "Розсилку не знайдено")
    if broadcast.status == BroadcastStatus.SENDING:
        raise HTTPException(409, "Розсилка вже виконується")
    if broadcast.status == BroadcastStatus.SENT:
        raise HTTPException(409, "Цю розсилку вже надіслано")

    await repo.update_broadcast(broadcast_id, {
        "status": BroadcastStatus.SENDING,
        "sent_count": 0, "failed_count": 0, "cursor_id": 0,
    })

    if settings.serverless:
        # Фонове завдання не переживе відповідь функції — порції візьме
        # на себе планувальник, що смикає /api/cron/broadcast-tick
        log.info("Serverless: розсилку %s поставлено в чергу для планувальника", broadcast_id)
    else:
        background.add_task(broadcast_service.run_to_completion, broadcast_id)

    return await repo.get_broadcast(broadcast_id)


@router.delete("/{broadcast_id}", status_code=204)
async def delete_broadcast(broadcast_id: int, repo: Repository = Depends(get_repo)):
    broadcast = await repo.get_broadcast(broadcast_id)
    if not broadcast:
        raise HTTPException(404, "Розсилку не знайдено")
    if broadcast.status == BroadcastStatus.SENDING:
        raise HTTPException(409, "Не можна видалити розсилку, яка виконується")
    await repo.delete_broadcast(broadcast_id)
