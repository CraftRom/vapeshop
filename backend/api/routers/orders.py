from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import require_staff
from api.schemas import OrderOut, OrderPatch
from shop.entities import STATUS_LABELS, OrderStatus
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services.shop_service import change_order_status
from shop.telegram import notify_user

router = APIRouter(dependencies=[Depends(require_staff)])


@router.get("", response_model=list[OrderOut])
async def list_orders(
    status: OrderStatus | None = None,
    search: str | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    repo: Repository = Depends(get_repo),
):
    return await repo.list_orders(status=status, search=search, limit=limit, offset=offset)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, repo: Repository = Depends(get_repo)):
    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")
    return order


@router.patch("/{order_id}", response_model=OrderOut)
async def patch_order(
    order_id: int, data: OrderPatch, repo: Repository = Depends(get_repo)
):
    order = await repo.get_order(order_id)
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")

    if data.admin_note is not None:
        await repo.update_order(order_id, {"admin_note": data.admin_note})

    if data.status and data.status != order.status:
        await change_order_status(repo, order, data.status)
        if order.user:
            await notify_user(
                order.user.tg_id,
                f"Замовлення №{order.id}: статус змінено на «{STATUS_LABELS[data.status]}».",
            )

    return await repo.get_order(order_id)
