from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from api.auth import require_staff
from api.schemas import BroadcastIn, BroadcastOut, ScheduleIn, SegmentIn
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


def _normalize_schedule(moment: datetime | None) -> datetime | None:
    """Округлює час запуску вниз до цілої години і приводить до UTC.

    Точність планувальника — година. Зберігати «14:37» означало б показувати
    в панелі час, якого система не обіцяє: реально розсилка пішла б о 15:00.
    Краще округлити явно й показати те, що станеться насправді.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)


@router.post("", response_model=BroadcastOut, status_code=201)
async def create_broadcast(data: BroadcastIn, repo: Repository = Depends(get_repo)):
    payload = data.model_dump(exclude={"segment"})
    payload["segment"] = data.segment.model_dump(exclude_none=True)

    scheduled = _normalize_schedule(payload.get("scheduled_at"))
    payload["scheduled_at"] = scheduled
    if scheduled:
        payload["status"] = BroadcastStatus.SCHEDULED
    return await repo.create_broadcast(payload)


@router.post("/{broadcast_id}/schedule", response_model=BroadcastOut)
async def schedule_broadcast(
    broadcast_id: int,
    data: ScheduleIn,
    repo: Repository = Depends(get_repo),
):
    """Ставить розсилку в чергу на конкретну годину."""
    broadcast = await repo.get_broadcast(broadcast_id)
    if not broadcast:
        raise HTTPException(404, "Розсилку не знайдено")
    if broadcast.status in (BroadcastStatus.SENDING, BroadcastStatus.SENT):
        raise HTTPException(409, "Розсилка вже виконується або надіслана")

    moment = _normalize_schedule(data.scheduled_at)
    # Порівнюємо з поточною годиною, а не з точним «зараз»: інакше о 14:05
    # неможливо було б поставити розсилку на 14:00, хоч планувальник
    # візьме її вже наступним тіком.
    current_hour = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    if moment < current_hour:
        raise HTTPException(422, "Час запуску вже минув")

    await repo.update_broadcast(broadcast_id, {
        "status": BroadcastStatus.SCHEDULED,
        "scheduled_at": moment,
    })
    return await repo.get_broadcast(broadcast_id)


@router.post("/{broadcast_id}/unschedule", response_model=BroadcastOut)
async def unschedule_broadcast(broadcast_id: int, repo: Repository = Depends(get_repo)):
    """Знімає розсилку з черги, повертаючи її в чернетки."""
    broadcast = await repo.get_broadcast(broadcast_id)
    if not broadcast:
        raise HTTPException(404, "Розсилку не знайдено")
    if broadcast.status != BroadcastStatus.SCHEDULED:
        raise HTTPException(409, "Ця розсилка не запланована")

    await repo.update_broadcast(broadcast_id, {
        "status": BroadcastStatus.DRAFT,
        "scheduled_at": None,
    })
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

    await repo.update_broadcast(broadcast_id, {
        "status": BroadcastStatus.SENDING,
        "sent_count": 0, "failed_count": 0, "cursor_id": 0,
    })

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
    await repo.delete_broadcast(broadcast_id)
