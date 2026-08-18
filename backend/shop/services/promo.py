from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shop.models import PromoCode, PromoType, PromoUsage


@dataclass
class PromoResult:
    ok: bool
    discount: Decimal = Decimal(0)
    promo: PromoCode | None = None
    error: str | None = None


async def apply(session: AsyncSession, code: str, user_id: int, subtotal: Decimal) -> PromoResult:
    promo = await session.scalar(select(PromoCode).where(func.upper(PromoCode.code) == code.strip().upper()))

    if not promo or not promo.is_active:
        return PromoResult(False, error="Такого промокоду немає")

    if promo.expires_at and promo.expires_at < datetime.now(timezone.utc):
        return PromoResult(False, error="Термін дії промокоду вичерпано")

    if promo.max_uses is not None and promo.used_count >= promo.max_uses:
        return PromoResult(False, error="Ліміт використань вичерпано")

    if subtotal < promo.min_order:
        return PromoResult(False, error=f"Мінімальна сума замовлення — {promo.min_order:.0f} грн")

    used_by_user = await session.scalar(
        select(func.count(PromoUsage.id)).where(
            PromoUsage.promo_id == promo.id, PromoUsage.user_id == user_id
        )
    )
    if used_by_user >= promo.per_user_limit:
        return PromoResult(False, error="Ви вже використали цей промокод")

    if promo.type == PromoType.PERCENT:
        discount = (subtotal * promo.value / Decimal(100)).quantize(Decimal("0.01"))
    else:
        discount = promo.value

    discount = min(discount, subtotal)
    return PromoResult(True, discount=discount, promo=promo)


async def register_usage(session: AsyncSession, promo_id: int, user_id: int, order_id: int) -> None:
    session.add(PromoUsage(promo_id=promo_id, user_id=user_id, order_id=order_id))
    promo = await session.get(PromoCode, promo_id)
    if promo:
        promo.used_count += 1
    await session.commit()
