from __future__ import annotations

import secrets
import string
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from shop.config import settings
from shop.models import BonusTx, Order, OrderStatus, User

ALPHABET = string.ascii_uppercase + string.digits


async def _unique_code(session: AsyncSession) -> str:
    while True:
        code = "".join(secrets.choice(ALPHABET) for _ in range(8))
        exists = await session.scalar(select(User.id).where(User.referral_code == code))
        if not exists:
            return code


async def get_or_create_user(
    session: AsyncSession,
    tg_id: int,
    username: str | None = None,
    first_name: str | None = None,
    referral_code: str | None = None,
) -> tuple[User, bool]:
    """Повертає (користувач, чи щойно створений)."""
    user = await session.scalar(select(User).where(User.tg_id == tg_id))
    if user:
        user.username = username or user.username
        user.first_name = first_name or user.first_name
        user.last_seen_at = func.now()
        await session.commit()
        return user, False

    referrer_id = None
    if referral_code:
        referrer = await session.scalar(select(User).where(User.referral_code == referral_code))
        if referrer:
            referrer_id = referrer.id

    user = User(
        tg_id=tg_id,
        username=username,
        first_name=first_name,
        referral_code=await _unique_code(session),
        referrer_id=referrer_id,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user, True


async def add_bonus(
    session: AsyncSession,
    user_id: int,
    amount: Decimal,
    reason: str,
    order_id: int | None = None,
) -> None:
    """Нараховує (+) або списує (−) бонуси разом із записом в історію."""
    session.add(BonusTx(user_id=user_id, amount=amount, reason=reason, order_id=order_id))
    await session.execute(
        update(User).where(User.id == user_id).values(bonus_balance=User.bonus_balance + amount)
    )
    await session.commit()


async def pay_referral_reward(session: AsyncSession, order: Order) -> Decimal | None:
    """Нараховує рефереру % від замовлення. Викликається один раз, при статусі DONE."""
    if order.referral_paid or order.status != OrderStatus.DONE:
        return None

    user = await session.get(User, order.user_id)
    if not user or not user.referrer_id:
        order.referral_paid = True
        await session.commit()
        return None

    reward = (order.total * Decimal(str(settings.referral_percent)) / Decimal(100)).quantize(Decimal("0.01"))
    if reward > 0:
        await add_bonus(session, user.referrer_id, reward, "referral", order.id)

    order.referral_paid = True
    await session.commit()
    return reward


async def user_stats(session: AsyncSession, user_id: int) -> dict:
    """Кількість замовлень, сума витрат, кількість рефералів."""
    orders_count, total_spent = (
        await session.execute(
            select(func.count(Order.id), func.coalesce(func.sum(Order.total), 0)).where(
                Order.user_id == user_id,
                Order.status.in_([OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DONE]),
            )
        )
    ).one()
    referrals = await session.scalar(select(func.count(User.id)).where(User.referrer_id == user_id))
    return {
        "orders_count": orders_count or 0,
        "total_spent": Decimal(total_spent or 0),
        "referrals": referrals or 0,
    }
