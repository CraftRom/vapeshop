from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import Principal, require_staff
from api.schemas import PanelNotificationOut, PanelNotificationPollOut
from shop.repo.base import Repository
from shop.repo.factory import get_repo

router = APIRouter(dependencies=[Depends(require_staff)])


def viewer_key(who: Principal) -> str:
    # Для DB-менеджера operator_id — стабільна ідентичність: зміна логіна не
    # повинна раптом зробити всю історію непрочитаною. Сисадмін із .env не
    # має рядка operators, тому для нього стабільним ключем лишається login.
    if who.operator_id:
        return f"staff:{who.operator_id}"
    return f"sysadmin:{who.login}"[:64]


@router.get("", response_model=list[PanelNotificationOut])
async def list_notifications(
    limit: int = Query(60, ge=1, le=200),
    who: Principal = Depends(require_staff),
    repo: Repository = Depends(get_repo),
):
    return await repo.list_panel_notifications(viewer_key(who), limit=limit)


@router.get("/poll", response_model=PanelNotificationPollOut)
async def poll_notifications(
    after_id: int | None = Query(None, ge=0),
    limit: int = Query(60, ge=1, le=200),
    who: Principal = Depends(require_staff),
    repo: Repository = Depends(get_repo),
):
    key = viewer_key(who)
    items = await repo.list_panel_notifications(key, limit=limit, after_id=after_id)
    if after_id is None:
        latest_id = max((int(item["id"]) for item in items), default=0)
    else:
        latest_id = max([int(after_id), *(int(item["id"]) for item in items)])
    return {
        "items": items,
        "unread_count": await repo.panel_notification_unread_count(key),
        "latest_id": latest_id,
    }


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: int,
    who: Principal = Depends(require_staff),
    repo: Repository = Depends(get_repo),
):
    if not await repo.mark_panel_notification_read(notification_id, viewer_key(who)):
        raise HTTPException(404, "Сповіщення не знайдено")
    return {"ok": True, "unread_count": await repo.panel_notification_unread_count(viewer_key(who))}


@router.post("/read-all")
async def mark_all_read(
    who: Principal = Depends(require_staff),
    repo: Repository = Depends(get_repo),
):
    key = viewer_key(who)
    changed = await repo.mark_all_panel_notifications_read(key)
    # Між вибіркою і commit могла з'явитися нова подія. Не брехати UI,
    # що unread=0: повертаємо фактичний стан після операції.
    return {"ok": True, "changed": changed, "unread_count": await repo.panel_notification_unread_count(key)}
