from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from api.auth import require_staff
from api.schemas import CustomerOut, CustomerPatch
from shop.repo.base import Repository
from shop.repo.factory import get_repo

router = APIRouter(dependencies=[Depends(require_staff)])


@router.get("", response_model=list[CustomerOut])
async def list_customers(
    search: str | None = None,
    blocked: bool | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    repo: Repository = Depends(get_repo),
):
    return await repo.list_users(search=search, blocked=blocked, limit=limit, offset=offset)


@router.patch("/{customer_id}", response_model=CustomerOut)
async def patch_customer(
    customer_id: int, data: CustomerPatch, repo: Repository = Depends(get_repo)
):
    if not await repo.get_user(customer_id):
        raise HTTPException(404, "Клієнта не знайдено")

    if data.is_blocked is not None:
        await repo.set_blocked(customer_id, data.is_blocked)

    if data.bonus_delta:
        await repo.add_bonus(customer_id, data.bonus_delta, data.bonus_reason)

    return await repo.get_user(customer_id)


@router.get("/{customer_id}/orders")
async def customer_orders(customer_id: int, repo: Repository = Depends(get_repo)):
    orders = await repo.list_orders(user_id=customer_id, limit=200)
    return [
        {
            "id": o.id, "status": o.status.value, "total": o.total,
            "created_at": o.created_at,
            "items": [{"name": ln.name, "qty": ln.qty, "price": ln.price} for ln in o.items],
        }
        for o in orders
    ]
