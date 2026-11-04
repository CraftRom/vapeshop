from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query

from api.auth import require_staff
from api.schemas import BroadcastIn, BroadcastOut, ScheduleIn, SegmentIn
from shop.config import settings
from shop.entities import BroadcastStatus
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services import broadcast as broadcast_service
from shop.services.broadcast_content import validate_content
from shop.services.broadcast_media import telegram_photo
from starlette.concurrency import run_in_threadpool

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


def _normalize_schedule(moment: datetime | None) -> datetime | None:
    """Приводить час до UTC без округлення, щоб не запустити розсилку раніше.

    Старі клієнти без часового поясу, як і раніше, передають UTC.
    Панель передає ISO 8601 з явним часовим поясом.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


@router.post("", response_model=BroadcastOut, status_code=201)
async def create_broadcast(data: BroadcastIn, repo: Repository = Depends(get_repo)):
    if data.client_key:
        existing = await repo.get_broadcast_by_client_key(data.client_key)
        if existing:
            return existing
    await preflight(data)
    payload = data.model_dump(exclude={"segment"})
    payload["segment"] = data.segment.model_dump(exclude_none=True)

    scheduled = _normalize_schedule(payload.get("scheduled_at"))
    payload["scheduled_at"] = scheduled
    if scheduled:
        if scheduled <= datetime.now(timezone.utc):
            raise HTTPException(422, 'Час запуску вже минув')
        payload["status"] = BroadcastStatus.SCHEDULED
    return await repo.create_broadcast(payload)


async def preflight(broadcast):
    try:
        validate_content(broadcast.text, broadcast.photo_url, broadcast.text_format,
                         broadcast.button_text, broadcast.button_url)
        if broadcast.photo_url:
            await run_in_threadpool(telegram_photo, broadcast.photo_url)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from None


@router.put('/{broadcast_id}', response_model=BroadcastOut)
async def update_draft(broadcast_id: int, data: BroadcastIn, repo: Repository = Depends(get_repo)):
    found = await repo.get_broadcast(broadcast_id)
    if not found:
        raise HTTPException(404, 'Розсилку не знайдено')
    if found.status != BroadcastStatus.DRAFT:
        raise HTTPException(409, 'Редагувати можна лише чернетку. Зніміть розсилку з черги або створіть копію')
    await preflight(data)
    payload = data.model_dump(exclude={'segment', 'client_key', 'scheduled_at'})
    payload['segment'] = data.segment.model_dump(exclude_none=True)
    if not await repo.transition_broadcast(broadcast_id, [BroadcastStatus.DRAFT], payload):
        raise HTTPException(409, 'Розсилка вже запущена. Оновіть список')
    return await repo.get_broadcast(broadcast_id)


@router.post("/{broadcast_id}/schedule", response_model=BroadcastOut)
async def schedule_broadcast(
    broadcast_id: int,
    data: ScheduleIn,
    repo: Repository = Depends(get_repo),
):
    """Ставить розсилку в чергу не раніше вибраного часу."""
    broadcast = await repo.get_broadcast(broadcast_id)
    if not broadcast:
        raise HTTPException(404, "Розсилку не знайдено")
    if broadcast.status in (BroadcastStatus.SENDING, BroadcastStatus.SENT):
        raise HTTPException(409, "Розсилка вже виконується або надіслана")
    await preflight(broadcast)

    moment = _normalize_schedule(data.scheduled_at)
    if moment <= datetime.now(timezone.utc):
        raise HTTPException(422, "Час запуску вже минув")

    if not await repo.transition_broadcast(broadcast_id,
            [BroadcastStatus.DRAFT, BroadcastStatus.SCHEDULED, BroadcastStatus.FAILED],
            {"status": BroadcastStatus.SCHEDULED, "scheduled_at": moment,
             "lease_owner": None, "lease_until": None}):
        raise HTTPException(409, "Розсилка вже виконується або надіслана")
    return await repo.get_broadcast(broadcast_id)


@router.post("/{broadcast_id}/unschedule", response_model=BroadcastOut)
async def unschedule_broadcast(broadcast_id: int, repo: Repository = Depends(get_repo)):
    """Знімає розсилку з черги, повертаючи її в чернетки."""
    broadcast = await repo.get_broadcast(broadcast_id)
    if not broadcast:
        raise HTTPException(404, "Розсилку не знайдено")
    if broadcast.status != BroadcastStatus.SCHEDULED:
        raise HTTPException(409, "Ця розсилка не запланована")

    if not await repo.transition_broadcast(broadcast_id, [BroadcastStatus.SCHEDULED],
            {"status": BroadcastStatus.DRAFT, "scheduled_at": None}):
        raise HTTPException(409, "Розсилка вже захоплена виконавцем")
    return await repo.get_broadcast(broadcast_id)


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
    await preflight(broadcast)

    if not await repo.transition_broadcast(broadcast_id,
            [BroadcastStatus.DRAFT, BroadcastStatus.SCHEDULED, BroadcastStatus.FAILED],
            {"status": BroadcastStatus.SENDING, "lease_owner": None,
             "lease_until": None, "finished_at": None}):
        raise HTTPException(409, "Розсилка вже виконується або надіслана")
    # Counters/cursor/journal survive retries. API exit before background task
    # starts is safe: scheduler also selects SENDING without an active lease.

    # Порції крутить фонове завдання самого API. Планувальник тут не
    # потрібен: це ручний запуск, адміністратор чекає результату зараз.
    background.add_task(broadcast_service.run_to_completion, broadcast_id, settings.broadcast_chunk)

    return await repo.get_broadcast(broadcast_id)


@router.get("/{broadcast_id}", response_model=BroadcastOut)
async def get_broadcast(broadcast_id: int, repo: Repository = Depends(get_repo)):
    found = await repo.get_broadcast(broadcast_id)
    if not found:
        raise HTTPException(404, "Розсилку не знайдено")
    return found


@router.delete("/{broadcast_id}", status_code=204)
async def delete_broadcast(broadcast_id: int, repo: Repository = Depends(get_repo)):
    broadcast = await repo.get_broadcast(broadcast_id)
    if not broadcast:
        raise HTTPException(404, "Розсилку не знайдено")
    if broadcast.status == BroadcastStatus.SENDING:
        raise HTTPException(409, "Не можна видалити розсилку, яка виконується")
    if not await repo.delete_broadcast(broadcast_id):
        raise HTTPException(409, "Розсилка вже захоплена виконавцем")


@router.get("/{broadcast_id}/deliveries")
async def broadcast_deliveries(broadcast_id: int, after: int = Query(0, ge=0),
                              limit: int = Query(100, ge=1, le=200),
                              repo: Repository = Depends(get_repo)):
    if not await repo.get_broadcast(broadcast_id):
        raise HTTPException(404, "Розсилку не знайдено")
    return await repo.list_broadcast_deliveries(broadcast_id, after, limit)
