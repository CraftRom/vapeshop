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
from shop.entities import (
    STATUS_LABELS, Order, OrderLine, OrderStatus, Promo, PromoType, User,
)
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
        shop = await get_shop_settings(repo)
        return PromoResult(
            False,
            error=f"Мінімальна сума замовлення — {promo.min_order:.0f} {shop.currency}",
        )

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
    if not shop.bonus_enabled:
        return Decimal(0)
    return max_bonus_for(subtotal, balance, shop.bonus_max_percent)


async def create_order(
    repo: Repository, user: User, *, contact_name: str, contact_phone: str,
    city: str, address: str, payment_method: str, comment: str | None = None,
    promo_code: str | None = None, use_bonus: bool = False,
    contact_surname: str | None = None, contact_patronymic: str | None = None,
    delivery_method: str | None = None, delivery_city_ref: str | None = None,
    delivery_warehouse_ref: str | None = None,
) -> tuple[Order | None, str | None]:
    lines = await repo.get_cart(user.id)
    if not lines:
        return None, "Кошик порожній"

    problems = await validate_cart(repo, user.id)
    if problems:
        return None, "Змінилася наявність:\n• " + "\n• ".join(problems)

    subtotal = sum((line.line_total for line in lines), Decimal(0))

    shop = await get_shop_settings(repo)

    promo_discount = Decimal(0)
    promo_id = None
    if promo_code:
        result = await check_promo(repo, promo_code, user.id, subtotal)
        if not result.ok:
            return None, result.error
        promo_discount, promo_id = result.discount, result.promo.id

    # Знижка за суму й промокод не додаються, а конкурують: діє більша.
    # Складання давало б несподівані подарунки на великих чеках, і власник
    # магазину помітив би це вже за виторгом.
    volume_discount = shop.volume_discount_for(subtotal)
    discount = max(promo_discount, volume_discount)
    if discount == volume_discount and volume_discount > promo_discount:
        promo_id = None  # промокод не застосувався, лічильник використань не рухаємо

    bonus_used = (
        await max_bonus_for_repo(repo, subtotal - discount, user.bonus_balance)
        if use_bonus and shop.bonus_enabled else Decimal(0)
    )
    total = max(Decimal(0), subtotal - discount - bonus_used)

    # Повний ПІБ одним рядком: на нього спираються пошук менеджера,
    # сповіщення і вся наявна історія замовлень
    full_name = " ".join(
        part for part in (
            (contact_surname or "").strip(),
            (contact_name or "").strip(),
            (contact_patronymic or "").strip(),
        ) if part
    ) or contact_name

    draft = Order(
        id=0, user_id=user.id, subtotal=subtotal, discount=discount,
        bonus_used=bonus_used, total=total, promo_code_id=promo_id,
        payment_method=payment_method, contact_name=full_name,
        contact_surname=(contact_surname or "").strip() or None,
        contact_patronymic=(contact_patronymic or "").strip() or None,
        contact_phone=contact_phone, delivery_city=city,
        delivery_address=address, comment=comment,
        # Коди можуть не прийти зовсім: якщо довідник недоступний,
        # вітрина дає вписати адресу руками. Прийняти замовлення без
        # кодів і уточнити в чаті дешевше, ніж втратити покупця.
        delivery_method=delivery_method or None,
        delivery_city_ref=(delivery_city_ref or "").strip() or None,
        delivery_warehouse_ref=(delivery_warehouse_ref or "").strip() or None,
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


# Куди можна перейти з кожного статусу.
#
# Перевірка потрібна не заради формальності: перехід одразу у «Виконано»
# нараховує реферальну винагороду й списує залишки повз оплату, а зворотний
# шлях із закритого замовлення повернув би бонуси й товар удруге.
# Маршрут статусів залежить від способу оплати.
#
# При оплаті карткою «Оплачене» — окремий стан: гроші приходять до
# відправки, і менеджер має бачити, чи вони вже надійшли. При накладеному
# платежі такого стану не існує взагалі: клієнт платить у відділенні при
# отриманні, тобто оплата й виконання — та сама подія. Пропонувати
# «Оплачене» в цьому випадку означало б просити менеджера відзначати те,
# чого він не бачить.
#
# «Прийняте» ставиться саме, коли менеджер відкриває замовлення в панелі:
# факт того, що його побачили, і є прийняттям. Окремої кнопки «підтвердити»
# більше немає — вона вимагала натискання, яке нічого не означало, крім
# «я подивився».
#
# «Виконане» поки ставлять руками — автоматичним воно стане, коли
# підключимо стеження за посилками.
_CARD_ROUTE: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.NEW: {OrderStatus.ACCEPTED, OrderStatus.CANCELLED},
    OrderStatus.ACCEPTED: {OrderStatus.PAID, OrderStatus.CANCELLED},
    OrderStatus.PAID: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.DONE, OrderStatus.CANCELLED},
    OrderStatus.DONE: set(),
    OrderStatus.CANCELLED: set(),
}

_COD_ROUTE: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.NEW: {OrderStatus.ACCEPTED, OrderStatus.CANCELLED},
    OrderStatus.ACCEPTED: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.DONE, OrderStatus.CANCELLED},
    OrderStatus.DONE: set(),
    OrderStatus.CANCELLED: set(),
}

# Спадок. Обидва стани прибрані з маршрутів, але лишились у базі:
# «Підтверджене» — крок, якого більше немає, «Оплачене» при накладеному
# платежі — залишок від часів спільного маршруту. Міграція переводить
# перше в «Прийняте», проте вихід уперед лишаємо обом: якщо якийсь рядок
# міграцію не зачепить, він має рухатись далі, а не застрягти назавжди.
for _route in (_CARD_ROUTE, _COD_ROUTE):
    _route[OrderStatus.CONFIRMED] = {OrderStatus.ACCEPTED, OrderStatus.CANCELLED}
_COD_ROUTE[OrderStatus.PAID] = {OrderStatus.SHIPPED, OrderStatus.CANCELLED}

# Кроки доріжки в панелі — саме ті, що менеджер бачить і може натиснути.
# Спадкові стани сюди не входять: показувати «Підтверджене» на нових
# замовленнях означало б повернути крок, який ми щойно прибрали.
_CARD_STAGES = (
    OrderStatus.NEW, OrderStatus.ACCEPTED, OrderStatus.PAID,
    OrderStatus.SHIPPED, OrderStatus.DONE,
)
_COD_STAGES = (
    OrderStatus.NEW, OrderStatus.ACCEPTED, OrderStatus.SHIPPED, OrderStatus.DONE,
)


def route_for(payment_method: str | None) -> dict[OrderStatus, set[OrderStatus]]:
    """Дозволені переходи для конкретного способу оплати."""
    return _COD_ROUTE if payment_method == "cod" else _CARD_ROUTE


def stages_for(payment_method: str | None) -> tuple[OrderStatus, ...]:
    """Послідовність кроків доріжки для цього способу оплати.

    При накладеному платежі «Оплачене» відсутнє: клієнт платить у
    відділенні при отриманні, тож оплата й виконання — та сама подія,
    і відзначати її окремо менеджеру нема з чого.
    """
    return _COD_STAGES if payment_method == "cod" else _CARD_STAGES


def next_statuses(order) -> list[OrderStatus]:
    """Куди можна перевести це замовлення просто зараз."""
    allowed = route_for(getattr(order, "payment_method", None)).get(order.status, set())
    return [s for s in OrderStatus if s in allowed]


# Сумісність: код, який не знає про спосіб оплати, працює за маршрутом
# картки — він ширший, тож нічого не заборонить помилково.
ALLOWED_TRANSITIONS = _CARD_ROUTE


def transition_error(
    current: OrderStatus,
    target: OrderStatus,
    payment_method: str | None = None,
) -> str | None:
    """Пояснення, чому перехід неможливий. None — якщо дозволений.

    payment_method потрібен, бо маршрут різний: при накладеному платежі
    стану «Оплачене» не існує, і пропонувати його менеджеру безглуздо.
    """
    if current == target:
        return None
    allowed = route_for(payment_method).get(current, set())
    if target in allowed:
        return None

    if not allowed:
        return (
            f"Замовлення вже {STATUS_LABELS[current].lower()} — змінити статус не можна."
        )
    names = ", ".join(f"«{STATUS_LABELS[s]}»" for s in
                      sorted(allowed, key=lambda x: x.value))
    return (
        f"Зі статусу «{STATUS_LABELS[current]}» можна перейти лише в {names}."
    )


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
    if not shop.referral_enabled or not shop.bonus_enabled:
        # Винагорода нараховується бонусами, тож вимкнені бонуси вимикають
        # і реферальну програму — інакше нарахування нікуди не подінеться
        return None
    reward = (order.total * shop.referral_percent / Decimal(100)).quantize(Decimal("0.01"))
    if reward > 0:
        await repo.add_bonus(user.referrer_id, reward, "referral", order.id)
    return reward
