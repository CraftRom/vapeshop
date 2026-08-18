from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shop.models import Order, OrderStatus, User

PAID_STATUSES = [OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DONE]

SEGMENTS = {
    "all": "Усі клієнти",
    "with_orders": "З покупками",
    "no_orders": "Без покупок",
    "inactive": "Не заходили N днів",
    "top_spenders": "Витратили більше N грн",
    "with_referrals": "Привели друзів",
}


def build_query(segment: dict) -> Select:
    """segment: {"type": "...", "days": 30, "min_total": 5000}"""
    stype = (segment or {}).get("type", "all")
    base = select(User).where(User.is_blocked.is_(False), User.age_confirmed.is_(True))

    paid_orders = (
        select(Order.user_id, func.sum(Order.total).label("spent"))
        .where(Order.status.in_(PAID_STATUSES))
        .group_by(Order.user_id)
        .subquery()
    )

    if stype == "with_orders":
        return base.join(paid_orders, paid_orders.c.user_id == User.id)

    if stype == "no_orders":
        return base.outerjoin(paid_orders, paid_orders.c.user_id == User.id).where(
            paid_orders.c.user_id.is_(None)
        )

    if stype == "inactive":
        days = int(segment.get("days", 30))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        return base.where(User.last_seen_at < cutoff)

    if stype == "top_spenders":
        min_total = float(segment.get("min_total", 1000))
        return base.join(
            paid_orders,
            and_(paid_orders.c.user_id == User.id, paid_orders.c.spent >= min_total),
        )

    if stype == "with_referrals":
        referrers = select(User.referrer_id).where(User.referrer_id.is_not(None)).distinct().subquery()
        return base.join(referrers, referrers.c.referrer_id == User.id)

    return base


async def count(session: AsyncSession, segment: dict) -> int:
    query = build_query(segment).with_only_columns(func.count(User.id)).order_by(None)
    return await session.scalar(query) or 0


async def tg_ids(session: AsyncSession, segment: dict) -> list[int]:
    query = build_query(segment).with_only_columns(User.tg_id)
    return list(await session.scalars(query))
