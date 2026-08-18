from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin
from api.schemas import CustomerOut, CustomerPatch
from shop.db import get_session
from shop.models import Order, OrderStatus, User
from shop.services.segments import PAID_STATUSES
from shop.services.users import add_bonus

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("", response_model=list[CustomerOut])
async def list_customers(
    search: str | None = None,
    blocked: bool | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    stats = (
        select(
            Order.user_id,
            func.count(Order.id).label("orders_count"),
            func.coalesce(func.sum(Order.total), 0).label("total_spent"),
        )
        .where(Order.status.in_(PAID_STATUSES))
        .group_by(Order.user_id)
        .subquery()
    )

    query = (
        select(
            User,
            func.coalesce(stats.c.orders_count, 0),
            func.coalesce(stats.c.total_spent, 0),
        )
        .outerjoin(stats, stats.c.user_id == User.id)
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if search:
        like = f"%{search}%"
        query = query.where(
            User.username.ilike(like) | User.first_name.ilike(like) | User.phone.ilike(like)
        )
    if blocked is not None:
        query = query.where(User.is_blocked.is_(blocked))

    rows = await session.execute(query)
    return [
        CustomerOut(
            **CustomerOut.model_validate(u).model_dump()
            | {"orders_count": cnt, "total_spent": Decimal(spent)}
        )
        for u, cnt, spent in rows
    ]


@router.patch("/{customer_id}", response_model=CustomerOut)
async def patch_customer(
    customer_id: int, data: CustomerPatch, session: AsyncSession = Depends(get_session)
):
    user = await session.get(User, customer_id)
    if not user:
        raise HTTPException(404, "Клієнта не знайдено")

    if data.is_blocked is not None:
        user.is_blocked = data.is_blocked
        await session.commit()

    if data.bonus_delta:
        await add_bonus(session, user.id, data.bonus_delta, data.bonus_reason)

    await session.refresh(user)
    return CustomerOut.model_validate(user)


@router.get("/{customer_id}/orders")
async def customer_orders(customer_id: int, session: AsyncSession = Depends(get_session)):
    orders = list(
        await session.scalars(
            select(Order).where(Order.user_id == customer_id).order_by(Order.created_at.desc())
        )
    )
    return [
        {
            "id": o.id,
            "status": o.status.value,
            "total": o.total,
            "created_at": o.created_at,
            "items": [{"name": i.name, "qty": i.qty, "price": i.price} for i in o.items],
        }
        for o in orders
    ]
