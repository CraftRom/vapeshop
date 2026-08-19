"""Бізнес-логіка магазину.

Працює тільки з інтерфейсом Repository, тому однаково виконується і на
Postgres, і на Firestore. Тут живуть усі правила — знижки, бонуси, залишки —
і саме цей модуль покривають тести.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from shop.config import settings
from shop.services.shop_settings import get_shop_settings
from shop.entities import Order, OrderLine, OrderStatus, Promo, PromoType, User
from shop.repo.base import Repository


# ---------------------------------------------------------------- користувачі

async def get_or_create_user(
    repo: Repository, tg_id: int, username=None, first_name=None, referral_code=None
) -> tuple[User, bool]:
    user = await repo.get_user_by_tg(tg_id)
    if user:
        await repo.touch_user(user, username, first_name)
        return user, False

    referrer_id = None
    if referral_code:
        referrer = await repo.get_user_by_referral_code(referral_code.strip())
        if referrer:
            referrer_id = referrer.id

    return await repo.create_user(tg_id, username, first_name, referrer_id), True


# ------------------------------------------------------------------ промокоди

@dataclass
class PromoResult:
    ok: bool
    discount: Decimal = Decimal(0)
    promo: Promo | None = None
    error: str | None = None


async def check_promo(
    repo: Repository, code: str, user_id: int, subtotal: Decimal
) -> PromoResult:
    promo = await repo.get_promo_by_code(code)

    if not promo or not promo.is_active:
        return PromoResult(False, error="Такого промокоду немає")

    if promo.expires_at:
        expires = promo.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if expires < datetime.now(timezone.utc):
            return PromoResult(False, error="Термін дії промокоду вичерпано")

    if promo.max_uses is not None and promo.used_count >= promo.max_uses:
        return PromoResult(False, error="Ліміт використань вичерпано")

    if subtotal < promo.min_order:
        return PromoResult(False, error=f"Мінімальна сума замовлення — {promo.min_order:.0f} грн")

    if await repo.promo_uses_by_user(promo.id, user_id) >= promo.per_user_limit:
        return PromoResult(False, error="Ви вже використали цей промокод")

    if promo.type == PromoType.PERCENT:
        discount = (subtotal * promo.value / Decimal(100)).quantize(Decimal("0.01"))
    else:
        discount = promo.value

    return PromoResult(True, discount=min(discount, subtotal), promo=promo)


# ---------------------------------------------------------------------- кошик

async def add_to_cart(repo: Repository, user_id: int, product_id: int, delta: int):
    product = await repo.get_product(product_id)
    if not product or not product.is_active:
        return None

    current = next(
        (line.qty for line in await repo.get_cart(user_id) if line.product_id == product_id), 0
    )
    new_qty = min(current + delta, product.stock)
    if new_qty <= 0:
        await repo.set_cart_qty(user_id, product_id, 0)
        return None

    await repo.set_cart_qty(user_id, product_id, new_qty)
    return new_qty


async def cart_subtotal(repo: Repository, user_id: int) -> Decimal:
    return sum((line.line_total for line in await repo.get_cart(user_id)), Decimal(0))


async def validate_cart(repo: Repository, user_id: int) -> list[str]:
    problems = []
    for line in await repo.get_cart(user_id):
        product = line.product
        if not product or not product.is_active:
            problems.append(f"«{product.name if product else 'товар'}» більше недоступний")
        elif product.stock < line.qty:
            problems.append(f"«{product.name}»: в наявності {product.stock} шт, у кошику {line.qty}")
    return problems


# ------------------------------------------------------------------ замовлення

def max_bonus_for(subtotal: Decimal, balance: Decimal, percent=None) -> Decimal:
    """percent=None — беремо дефолт із .env (для викликів без доступу до бази)."""
    if percent is None:
        percent = settings.bonus_max_percent
    cap = (subtotal * Decimal(str(percent)) / Decimal(100)).quantize(Decimal("0.01"))
    return max(Decimal(0), min(cap, balance))


async def max_bonus_for_repo(repo, subtotal: Decimal, balance: Decimal) -> Decimal:
    shop = await get_shop_settings(repo)
    return max_bonus_for(subtotal, balance, shop.bonus_max_percent)


async def create_order(
    repo: Repository, user: User, *, contact_name: str, contact_phone: str,
    city: str, address: str, payment_method: str, comment: str | None = None,
    promo_code: str | None = None, use_bonus: bool = False,
) -> tuple[Order | None, str | None]:
    lines = await repo.get_cart(user.id)
    if not lines:
        return None, "Кошик порожній"

    problems = await validate_cart(repo, user.id)
    if problems:
        return None, "Змінилася наявність:\n• " + "\n• ".join(problems)

    subtotal = sum((line.line_total for line in lines), Decimal(0))

    discount = Decimal(0)
    promo_id = None
    if promo_code:
        result = await check_promo(repo, promo_code, user.id, subtotal)
        if not result.ok:
            return None, result.error
        discount, promo_id = result.discount, result.promo.id

    bonus_used = (
        await max_bonus_for_repo(repo, subtotal - discount, user.bonus_balance)
        if use_bonus else Decimal(0)
    )
    total = max(Decimal(0), subtotal - discount - bonus_used)

    draft = Order(
        id=0, user_id=user.id, subtotal=subtotal, discount=discount,
        bonus_used=bonus_used, total=total, promo_code_id=promo_id,
        payment_method=payment_method, contact_name=contact_name,
        contact_phone=contact_phone, delivery_city=city,
        delivery_address=address, comment=comment,
    )
    order_lines = [
        OrderLine(product_id=line.product_id, name=line.product.name,
                  price=line.product.price, qty=line.qty)
        for line in lines
    ]
    order = await repo.create_order(draft, order_lines)

    for line in lines:
        await repo.adjust_stock(line.product_id, -line.qty)

    if promo_id:
        await repo.register_promo_use(promo_id, user.id, order.id)
    if bonus_used > 0:
        await repo.add_bonus(user.id, -bonus_used, "spend", order.id)
        user.bonus_balance -= bonus_used

    await repo.clear_cart(user.id)
    return order, None


async def change_order_status(
    repo: Repository, order: Order, status: OrderStatus
) -> Decimal | None:
    """Змінює статус. Повертає нараховану реферальну винагороду, якщо була."""
    previous = order.status
    if previous == status:
        return None

    await repo.update_order(order.id, {"status": status})
    order.status = status

    became_paid = previous not in _COUNTED and status in _COUNTED
    left_paid = previous in _COUNTED and status not in _COUNTED

    if became_paid:
        await _bump_user_totals(repo, order, +1)
    elif left_paid:
        await _bump_user_totals(repo, order, -1)

    if status == OrderStatus.DONE:
        return await _pay_referral(repo, order)

    if status == OrderStatus.CANCELLED and previous != OrderStatus.CANCELLED:
        for line in order.items:
            if line.product_id:
                await repo.adjust_stock(line.product_id, line.qty)
        if order.bonus_used > 0:
            await repo.add_bonus(order.user_id, order.bonus_used, "refund", order.id)

    return None


_COUNTED = (OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DONE)


async def _bump_user_totals(repo: Repository, order: Order, sign: int) -> None:
    """Тримає денормалізовані лічильники клієнта в актуальному стані."""
    user = await repo.get_user(order.user_id)
    if not user:
        return
    await repo.update_user_totals(
        user.id,
        orders_delta=sign,
        spent_delta=order.total * sign,
    )


async def _pay_referral(repo: Repository, order: Order) -> Decimal | None:
    if order.referral_paid:
        return None

    user = await repo.get_user(order.user_id)
    await repo.update_order(order.id, {"referral_paid": True})
    order.referral_paid = True

    if not user or not user.referrer_id:
        return None

    shop = await get_shop_settings(repo)
    reward = (order.total * shop.referral_percent / Decimal(100)).quantize(Decimal("0.01"))
    if reward > 0:
        await repo.add_bonus(user.referrer_id, reward, "referral", order.id)
    return reward
