from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from shop.config import settings
from shop.models import Order, OrderItem, OrderStatus, Product, User
from shop.services import cart as cart_service
from shop.services import promo as promo_service
from shop.services import users as users_service

STATUS_LABELS = {
    OrderStatus.NEW: "Нове",
    OrderStatus.CONFIRMED: "Підтверджене",
    OrderStatus.PAID: "Оплачене",
    OrderStatus.SHIPPED: "Відправлене",
    OrderStatus.DONE: "Виконане",
    OrderStatus.CANCELLED: "Скасоване",
}


def max_bonus_for(subtotal: Decimal, balance: Decimal) -> Decimal:
    """Скільки бонусів реально можна списати на це замовлення."""
    cap = (subtotal * Decimal(str(settings.bonus_max_percent)) / Decimal(100)).quantize(Decimal("0.01"))
    return max(Decimal(0), min(cap, balance))


async def create_from_cart(
    session: AsyncSession,
    user: User,
    *,
    contact_name: str,
    contact_phone: str,
    city: str,
    address: str,
    payment_method: str,
    comment: str | None = None,
    promo_code: str | None = None,
    use_bonus: bool = False,
) -> tuple[Order | None, str | None]:
    items = await cart_service.get_items(session, user.id)
    if not items:
        return None, "Кошик порожній"

    problems = await cart_service.validate_stock(session, user.id)
    if problems:
        return None, "Змінилася наявність:\n• " + "\n• ".join(problems)

    subtotal = sum((i.product.price * i.qty for i in items), Decimal(0))

    discount = Decimal(0)
    promo_id = None
    if promo_code:
        res = await promo_service.apply(session, promo_code, user.id, subtotal)
        if not res.ok:
            return None, res.error
        discount = res.discount
        promo_id = res.promo.id

    bonus_used = Decimal(0)
    if use_bonus:
        bonus_used = max_bonus_for(subtotal - discount, user.bonus_balance)

    total = max(Decimal(0), subtotal - discount - bonus_used)

    order = Order(
        user_id=user.id,
        subtotal=subtotal,
        discount=discount,
        bonus_used=bonus_used,
        total=total,
        promo_code_id=promo_id,
        payment_method=payment_method,
        contact_name=contact_name,
        contact_phone=contact_phone,
        delivery_city=city,
        delivery_address=address,
        comment=comment,
    )
    session.add(order)
    await session.flush()

    for item in items:
        session.add(
            OrderItem(
                order_id=order.id,
                product_id=item.product_id,
                name=item.product.name,
                price=item.product.price,
                qty=item.qty,
            )
        )
        product = await session.get(Product, item.product_id)
        if product:
            product.stock = max(0, product.stock - item.qty)

    await session.commit()

    if promo_id:
        await promo_service.register_usage(session, promo_id, user.id, order.id)
    if bonus_used > 0:
        await users_service.add_bonus(session, user.id, -bonus_used, "spend", order.id)

    await cart_service.clear(session, user.id)
    await session.refresh(order)
    return order, None


async def change_status(session: AsyncSession, order: Order, status: OrderStatus) -> Decimal | None:
    """Змінює статус. При DONE нараховує реферальну винагороду, при CANCELLED повертає залишки."""
    previous = order.status
    order.status = status
    await session.commit()

    if status == OrderStatus.DONE:
        return await users_service.pay_referral_reward(session, order)

    if status == OrderStatus.CANCELLED and previous != OrderStatus.CANCELLED:
        for item in order.items:
            if item.product_id:
                product = await session.get(Product, item.product_id)
                if product:
                    product.stock += item.qty
        if order.bonus_used > 0:
            await users_service.add_bonus(session, order.user_id, order.bonus_used, "refund", order.id)
        await session.commit()

    return None
