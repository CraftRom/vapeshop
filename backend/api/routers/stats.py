from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin
from api.schemas import SeriesPoint, StatsOut, TopProduct
from shop.db import get_session
from shop.models import Order, OrderItem, OrderStatus, Product, User
from shop.services.segments import PAID_STATUSES

router = APIRouter(dependencies=[Depends(require_admin)])


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


@router.get("/summary", response_model=StatsOut)
async def summary(days: int = Query(30, ge=1, le=365), session: AsyncSession = Depends(get_session)):
    since = _since(days)
    paid = Order.status.in_(PAID_STATUSES)

    revenue_total = await session.scalar(
        select(func.coalesce(func.sum(Order.total), 0)).where(paid)
    )
    revenue_period = await session.scalar(
        select(func.coalesce(func.sum(Order.total), 0)).where(paid, Order.created_at >= since)
    )
    orders_total = await session.scalar(select(func.count(Order.id)))
    orders_new = await session.scalar(
        select(func.count(Order.id)).where(Order.status == OrderStatus.NEW)
    )
    paid_count = await session.scalar(select(func.count(Order.id)).where(paid)) or 0
    customers_total = await session.scalar(select(func.count(User.id)))
    customers_period = await session.scalar(
        select(func.count(User.id)).where(User.created_at >= since)
    )
    low_stock = await session.scalar(
        select(func.count(Product.id)).where(Product.is_active.is_(True), Product.stock < 5)
    )

    avg_check = Decimal(revenue_total or 0) / paid_count if paid_count else Decimal(0)

    return StatsOut(
        revenue_total=Decimal(revenue_total or 0),
        revenue_period=Decimal(revenue_period or 0),
        orders_total=orders_total or 0,
        orders_new=orders_new or 0,
        customers_total=customers_total or 0,
        customers_period=customers_period or 0,
        avg_check=avg_check.quantize(Decimal("0.01")),
        low_stock=low_stock or 0,
    )


@router.get("/series", response_model=list[SeriesPoint])
async def series(days: int = Query(30, ge=7, le=365), session: AsyncSession = Depends(get_session)):
    since = _since(days)
    day = func.date_trunc("day", Order.created_at).label("day")
    rows = await session.execute(
        select(day, func.coalesce(func.sum(Order.total), 0), func.count(Order.id))
        .where(Order.status.in_(PAID_STATUSES), Order.created_at >= since)
        .group_by(day)
        .order_by(day)
    )
    return [
        SeriesPoint(date=d.strftime("%Y-%m-%d"), revenue=Decimal(rev), orders=cnt)
        for d, rev, cnt in rows
    ]


@router.get("/top-products", response_model=list[TopProduct])
async def top_products(
    days: int = Query(30, ge=1, le=365),
    limit: int = Query(10, le=50),
    session: AsyncSession = Depends(get_session),
):
    rows = await session.execute(
        select(
            OrderItem.name,
            func.sum(OrderItem.qty).label("qty"),
            func.sum(OrderItem.price * OrderItem.qty).label("revenue"),
        )
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.status.in_(PAID_STATUSES), Order.created_at >= _since(days))
        .group_by(OrderItem.name)
        .order_by(func.sum(OrderItem.price * OrderItem.qty).desc())
        .limit(limit)
    )
    return [TopProduct(name=name, qty=qty, revenue=Decimal(revenue)) for name, qty, revenue in rows]


@router.get("/status-breakdown")
async def status_breakdown(session: AsyncSession = Depends(get_session)):
    rows = await session.execute(
        select(Order.status, func.count(Order.id)).group_by(Order.status)
    )
    return [{"status": status.value, "count": count} for status, count in rows]
