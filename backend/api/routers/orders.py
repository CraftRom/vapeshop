from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api.auth import require_admin
from api.schemas import OrderOut, OrderPatch
from shop.db import get_session
from shop.models import Order, OrderStatus
from shop.services.orders import STATUS_LABELS, change_status
from shop.telegram import notify_user

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("", response_model=list[OrderOut])
async def list_orders(
    status: OrderStatus | None = None,
    search: str | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
):
    query = (
        select(Order)
        .options(selectinload(Order.items), selectinload(Order.user))
        .order_by(Order.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if status:
        query = query.where(Order.status == status)
    if search:
        like = f"%{search}%"
        query = query.where(
            Order.contact_name.ilike(like) | Order.contact_phone.ilike(like)
        )
    return list(await session.scalars(query))


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: int, session: AsyncSession = Depends(get_session)):
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items), selectinload(Order.user))
    )
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")
    return order


@router.patch("/{order_id}", response_model=OrderOut)
async def patch_order(
    order_id: int, data: OrderPatch, session: AsyncSession = Depends(get_session)
):
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.items), selectinload(Order.user))
    )
    if not order:
        raise HTTPException(404, "Замовлення не знайдено")

    if data.admin_note is not None:
        order.admin_note = data.admin_note
        await session.commit()

    if data.status and data.status != order.status:
        await change_status(session, order, data.status)
        if order.user:
            await notify_user(
                order.user.tg_id,
                f"Замовлення №{order.id}: статус змінено на «{STATUS_LABELS[data.status]}».",
            )

    await session.refresh(order)
    return order
