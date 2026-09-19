"""Репозиторій поверх SQLAlchemy — для власного сервера."""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shop import models as m
from shop.entities import (
    Operator, OperatorRole, OrderMessage, SupportMessage, SupportThread, Wishlist,
    Broadcast, BroadcastStatus, CartLine, Category, Order,
    OrderLine, OrderStatus, Product, Promo, Stats, User,
)
from shop.repo.base import Repository

ALPHABET = string.ascii_uppercase + string.digits
# Для статистики продаж «підтвердженим» є замовлення, яке вже вийшло
# зі стану NEW. CRM-синхронізація послідовно проєктує пізніші статуси
# SalesDrive на локальний workflow, тому тут не треба дублювати таблицю
# CRM-ID: локальний стан є технічним індексом пройденого етапу.
CONFIRMED_SQL = [
    OrderStatus.CONFIRMED, OrderStatus.ACCEPTED, OrderStatus.PAID,
    OrderStatus.SHIPPED, OrderStatus.DONE,
]
SHIPPED_SQL = [OrderStatus.SHIPPED, OrderStatus.DONE]
CONFIRMED_VALUES = frozenset(status.value for status in CONFIRMED_SQL)
SHIPPED_VALUES = frozenset(status.value for status in SHIPPED_SQL)
CARD_RECEIVED_VALUES = frozenset({
    OrderStatus.PAID.value, OrderStatus.SHIPPED.value, OrderStatus.DONE.value,
})


def _change(now: Decimal, before: Decimal) -> float | None:
    """Зміна у відсотках до попереднього періоду.

    None, а не нуль, коли порівнювати нема з чим: нуль читається як «без
    змін», а це протилежне до «даних за той період немає». Різниця
    важлива в перший місяць роботи магазину.
    """
    if not before:
        return None
    return round(float((now - before) / before * 100), 1)


def _dec(value) -> Decimal:
    return Decimal(str(value or 0))


def _maybe_dec(value) -> Decimal | None:
    """Decimal для CRM-числа, але None якщо поля справді немає.

    Нуль і відсутнє значення — різні речі: ``payedAmount=0`` означає, що
    SalesDrive явно не бачить оплати; ``None`` — що поле не прийшло й можна
    застосувати бізнес-правило/запасне джерело.
    """
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError):
        return None


def _snapshot(row) -> dict:
    value = getattr(row, "crm_snapshot", None)
    return value if isinstance(value, dict) else {}


def _stats_payment_method(row, snapshot: dict | None = None) -> str:
    method = str(getattr(row, "payment_method", "") or "").strip().lower()
    if method in {"card", "cod"}:
        return method
    snap = snapshot or _snapshot(row)
    text = " ".join(str(snap.get(key) or "") for key in ("paymentMethod", "paymentMethodRaw"))
    text = text.strip().lower()
    if any(token in text for token in ("карт", "card", "privat", "приват")):
        return "card"
    if any(token in text for token in ("наклад", "післяплат", "cod", "cash on delivery")):
        return "cod"
    return method or "unknown"


def stats_finance_values(status, payment_method, total, snapshot=None) -> dict:
    """Єдине фінансове правило статистики.

    ``confirmed`` — замовлення вже підтверджено/в роботі або пішло далі.
    ``received`` — гроші, які можна вважати отриманими зараз:
      * фактичний payedAmount/restPay із SalesDrive;
      * карткова оплата після локального PAID/SHIPPED/DONE.
        Для CRM це відповідає правилу «Відправлений або наступний етап»,
        бо CRM progression переводить локальний стан у SHIPPED/DONE.
    Накладений платіж без фактичного CRM-платежу лишається ``expected`` —
    ми не називаємо грошима на рахунку те, що ще має прийти від перевізника.

    Функція чиста й окремо тестується: сторінка замовлення та статистика не
    повинні мати дві різні версії одного бізнес-правила.
    """
    try:
        status_value = status.value
    except AttributeError:
        status_value = str(status or "")
    confirmed = status_value in CONFIRMED_VALUES
    shipped = status_value in SHIPPED_VALUES
    snap = snapshot if isinstance(snapshot, dict) else {}
    amount = _maybe_dec(snap.get("paymentAmount"))
    if amount is None or amount <= 0:
        amount = _dec(total)
    amount = max(Decimal(0), amount)

    paid = _maybe_dec(snap.get("payedAmount"))
    rest = _maybe_dec(snap.get("restPay"))
    if paid is None and rest is not None and amount > 0:
        paid = amount - rest
    actual = max(Decimal(0), min(amount, paid or Decimal(0)))

    method = str(payment_method or "").lower()
    card_stage_paid = method == "card" and status_value in CARD_RECEIVED_VALUES
    received = amount if (confirmed and card_stage_paid and amount > 0) else actual
    received = max(Decimal(0), min(amount, received)) if confirmed else Decimal(0)
    calculated = max(Decimal(0), received - actual) if confirmed else Decimal(0)
    expected = max(Decimal(0), amount - received) if confirmed else Decimal(0)

    return {
        "total": amount,
        "confirmed": confirmed,
        "shipped": shipped,
        "actual_received": actual if confirmed else Decimal(0),
        "calculated_received": calculated,
        "received": received,
        "expected": expected,
    }


def _row_finance(row) -> dict:
    snap = _snapshot(row)
    return stats_finance_values(
        getattr(row, "status", None),
        _stats_payment_method(row, snap),
        getattr(row, "total", 0),
        snap,
    )


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _in_window(value: datetime, since: datetime, until: datetime | None = None) -> bool:
    moment = _aware(value)
    return moment >= since and (until is None or moment < until)


def user_search_key(username, first_name, phone) -> str:
    return " ".join(filter(None, [username, first_name, phone])).lower()


# --------------------------------------------------------------- перетворення

def _user(row: m.User | None) -> User | None:
    if row is None:
        return None
    return User(
        id=row.id, tg_id=row.tg_id, referral_code=row.referral_code,
        username=row.username, first_name=row.first_name, phone=row.phone,
        full_name=row.full_name, age_confirmed=row.age_confirmed,
        chat_order_id=row.chat_order_id,
        is_blocked=row.is_blocked, bot_reachable=row.bot_reachable,
        referrer_id=row.referrer_id,
        bonus_balance=_dec(row.bonus_balance), orders_count=row.orders_count,
        total_spent=_dec(row.total_spent), referrals_count=row.referrals_count,
        created_at=row.created_at, last_seen_at=row.last_seen_at,
    )


def _category(row, products_count: int = 0) -> Category:
    return Category(
        id=row.id, name=row.name, description=row.description,
        sort_order=row.sort_order, is_active=row.is_active,
        products_count=products_count,
    )


def _product(row, category_name: str | None = None) -> Product | None:
    if row is None:
        return None
    return Product(
        id=row.id, category_id=row.category_id, name=row.name, sku=row.sku,
        price=_dec(row.price), description=row.description,
        old_price=_dec(row.old_price) if row.old_price is not None else None,
        stock=row.stock, photo_file_id=row.photo_file_id, photo_url=row.photo_url,
        sort_order=row.sort_order, is_active=row.is_active,
        category_name=category_name, name_lower=row.name_lower or row.name.lower(),
    )


def _order(row, with_user: bool = False) -> Order | None:
    if row is None:
        return None
    return Order(
        id=row.id, user_id=row.user_id, status=OrderStatus(row.status.value),
        subtotal=_dec(row.subtotal), discount=_dec(row.discount),
        bonus_used=_dec(row.bonus_used), total=_dec(row.total),
        promo_code_id=row.promo_code_id, payment_method=row.payment_method,
        receipt_file_id=row.receipt_file_id, contact_name=row.contact_name,
        contact_surname=row.contact_surname, contact_patronymic=row.contact_patronymic,
        contact_phone=row.contact_phone, delivery_city=row.delivery_city,
        delivery_address=row.delivery_address,
        delivery_method=row.delivery_method,
        delivery_city_ref=row.delivery_city_ref,
        delivery_warehouse_ref=row.delivery_warehouse_ref,
        comment=row.comment,
        admin_note=row.admin_note, tracking_number=row.tracking_number,
        waybill_ref=row.waybill_ref, waybill_source=row.waybill_source,
        waybill_cost=_dec(row.waybill_cost) if row.waybill_cost is not None else None,
        crm_id=row.crm_id, crm_status_id=row.crm_status_id, crm_status_name=row.crm_status_name,
        crm_state=row.crm_state or "", crm_error=row.crm_error,
        crm_attempts=row.crm_attempts or 0, crm_synced_at=row.crm_synced_at,
        crm_snapshot=row.crm_snapshot, crm_fetched_at=row.crm_fetched_at,
        operator_id=row.operator_id, operator_name=row.operator_name or "",
        referral_paid=row.referral_paid,
        created_at=row.created_at, search_key=row.search_key or "",
        items=[
            OrderLine(id=i.id, product_id=i.product_id, name=i.name,
                      price=_dec(i.price), qty=i.qty)
            for i in row.items
        ],
        user=_user(row.user) if with_user and row.user else None,
    )


def _promo(row) -> Promo | None:
    if row is None:
        return None
    from shop.entities import PromoType
    return Promo(
        id=row.id, code=row.code, type=PromoType(row.type.value), value=_dec(row.value),
        min_order=_dec(row.min_order), max_uses=row.max_uses,
        per_user_limit=row.per_user_limit, used_count=row.used_count,
        expires_at=row.expires_at, is_active=row.is_active, created_at=row.created_at,
    )


def _broadcast(row) -> Broadcast | None:
    if row is None:
        return None
    return Broadcast(
        id=row.id, title=row.title, text=row.text, photo_url=row.photo_url,
        button_text=row.button_text, button_url=row.button_url,
        segment=row.segment or {}, status=BroadcastStatus(row.status.value),
        sent_count=row.sent_count, failed_count=row.failed_count,
        cursor_id=row.cursor_id, scheduled_at=row.scheduled_at,
        created_at=row.created_at, finished_at=row.finished_at,
    )


def _not_below_zero(expression):
    """Значення виразу, але не менше нуля.

    Написано через CASE, а не func.max(0, x) і не GREATEST, і це важливо.

    func.max(0, x) компілюється в max(0, x). У SQLite це звичайна функція
    від двох аргументів, тому тести проходили роками. У Postgres max() —
    агрегатна функція від одного аргументу, і кожне оформлення замовлення
    падало з «function max(integer, integer) does not exist».

    GREATEST був би правильним для Postgres, але його немає в SQLite, на
    якому ганяються тести. CASE працює однаково скрізь — і саме тому
    розходження діалектів тут більше неможливе.
    """
    return case((expression < 0, 0), else_=expression)



class SqlRepository(Repository):
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def _commit(self) -> None:
        """Фіксує зміни й скидає кеш ORM.

        Частина методів змінює дані атомарним UPDATE повз ORM — так
        безпечніше при одночасних запитах. Але сесія створена з
        expire_on_commit=False, тож у пам'яті лишалася б стара копія
        обʼєкта, і наступне читання в тому ж запиті віддавало б, скажімо,
        доспис бонусів, якого вже немає. Тому після кожного такого запису
        кеш явно скидаємо.
        """
        await self.s.commit()
        self.s.expire_all()

    # ------------------------------------------------------------ users

    async def get_user_by_tg(self, tg_id: int) -> User | None:
        return _user(await self.s.scalar(select(m.User).where(m.User.tg_id == tg_id)))

    async def get_user(self, user_id: int) -> User | None:
        return _user(await self.s.get(m.User, user_id))

    async def get_user_by_referral_code(self, code: str) -> User | None:
        return _user(await self.s.scalar(select(m.User).where(m.User.referral_code == code)))

    async def _unique_code(self) -> str:
        while True:
            code = "".join(secrets.choice(ALPHABET) for _ in range(8))
            if not await self.s.scalar(select(m.User.id).where(m.User.referral_code == code)):
                return code

    async def create_user(self, tg_id, username, first_name, referrer_id) -> User:
        row = m.User(
            tg_id=tg_id, username=username, first_name=first_name,
            referral_code=await self._unique_code(), referrer_id=referrer_id,
            search_key=user_search_key(username, first_name, None),
        )
        self.s.add(row)
        if referrer_id:
            await self.s.execute(
                update(m.User).where(m.User.id == referrer_id)
                .values(referrals_count=m.User.referrals_count + 1)
            )
        await self._commit()
        await self.s.refresh(row)
        return _user(row)

    async def touch_user(self, user, username, first_name) -> User:
        await self.s.execute(
            update(m.User).where(m.User.id == user.id).values(
                username=username or user.username,
                first_name=first_name or user.first_name,
                last_seen_at=datetime.now(timezone.utc),
                search_key=user_search_key(
                    username or user.username, first_name or user.first_name, user.phone
                ),
            )
        )
        await self._commit()
        user.username = username or user.username
        user.first_name = first_name or user.first_name
        return user

    async def set_user_referrer(self, user, referrer_id: int) -> None:
        await self.s.execute(
            update(m.User).where(m.User.id == user.id).values(referrer_id=referrer_id)
        )
        await self.s.execute(
            update(m.User).where(m.User.id == referrer_id)
            .values(referrals_count=m.User.referrals_count + 1)
        )
        await self._commit()
        user.referrer_id = referrer_id

    async def confirm_age(self, user) -> None:
        await self.s.execute(
            update(m.User).where(m.User.id == user.id).values(age_confirmed=True)
        )
        await self._commit()
        user.age_confirmed = True

    async def set_blocked(self, user_id: int, blocked: bool) -> User | None:
        row = await self.s.get(m.User, user_id)
        if not row:
            return None
        row.is_blocked = blocked
        await self.s.commit()
        return _user(row)

    async def add_bonus(self, user_id, amount, reason, order_id=None) -> None:
        self.s.add(m.BonusTx(user_id=user_id, amount=amount, reason=reason, order_id=order_id))
        await self.s.execute(
            update(m.User).where(m.User.id == user_id)
            .values(bonus_balance=m.User.bonus_balance + amount)
        )
        await self._commit()

    async def update_user_totals(self, user_id, orders_delta, spent_delta) -> None:
        await self.s.execute(
            update(m.User).where(m.User.id == user_id).values(
                orders_count=_not_below_zero(m.User.orders_count + orders_delta),
                total_spent=_not_below_zero(m.User.total_spent + spent_delta),
            )
        )
        await self._commit()

    async def list_users(self, search=None, blocked=None, limit=100, offset=0) -> list[User]:
        query = select(m.User).order_by(m.User.created_at.desc()).limit(limit).offset(offset)
        if search:
            query = query.where(m.User.search_key.like(f"%{search.lower()}%"))
        if blocked is not None:
            query = query.where(m.User.is_blocked.is_(blocked))
        return [_user(r) for r in await self.s.scalars(query)]

    # ---------------------------------------------------------- catalog

    async def list_categories(self, only_active=False) -> list[Category]:
        counts = (
            select(m.Product.category_id, func.count(m.Product.id).label("cnt"))
            .group_by(m.Product.category_id).subquery()
        )
        query = (
            select(m.Category, func.coalesce(counts.c.cnt, 0))
            .outerjoin(counts, counts.c.category_id == m.Category.id)
            .order_by(m.Category.sort_order, m.Category.name)
        )
        if only_active:
            query = query.where(m.Category.is_active.is_(True))
        return [_category(row, cnt) for row, cnt in await self.s.execute(query)]

    async def get_category(self, category_id) -> Category | None:
        row = await self.s.get(m.Category, category_id)
        return _category(row) if row else None

    async def create_category(self, data: dict) -> Category:
        row = m.Category(**data)
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)
        return _category(row)

    async def update_category(self, category_id, data: dict) -> Category | None:
        row = await self.s.get(m.Category, category_id)
        if not row:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.s.commit()
        return _category(row)

    async def delete_category(self, category_id) -> int:
        result = await self.s.execute(
            update(m.Product)
            .where(m.Product.category_id == category_id, m.Product.is_active.is_(True))
            .values(is_active=False)
        )
        await self.s.execute(
            update(m.Category).where(m.Category.id == category_id).values(is_active=False)
        )
        await self._commit()
        return int(result.rowcount or 0)

    async def list_products(
        self, category_id=None, search=None, only_active=False, limit=500, offset=0
    ) -> list[Product]:
        query = (
            select(m.Product, m.Category.name)
            .join(m.Category, m.Category.id == m.Product.category_id)
            .order_by(m.Product.sort_order, m.Product.name)
            .limit(limit).offset(offset)
        )
        if category_id:
            query = query.where(m.Product.category_id == category_id)
        if search:
            query = query.where(or_(m.Product.name_lower.like(f"%{search.lower()}%"), m.Product.sku.ilike(f"%{search}%")))
        if only_active:
            query = query.where(m.Product.is_active.is_(True))
        return [_product(row, name) for row, name in await self.s.execute(query)]

    async def products_by_ids(self, ids) -> list:
        if not ids:
            return []
        rows = await self.s.scalars(
            select(m.Product).where(m.Product.id.in_(list(ids)))
        )
        return [_product(r) for r in rows]

    async def count_products(self, category_id, only_active=True) -> int:
        query = select(func.count(m.Product.id)).where(m.Product.category_id == category_id)
        if only_active:
            query = query.where(m.Product.is_active.is_(True))
        return await self.s.scalar(query) or 0

    async def get_product(self, product_id) -> Product | None:
        return _product(await self.s.get(m.Product, product_id))

    async def create_product(self, data: dict) -> Product:
        data = dict(data)
        if not data.get("sku"):
            from shop.services.product_io import generate_sku
            data["sku"] = await generate_sku(self)
        data["name_lower"] = data["name"].lower()
        row = m.Product(**data)
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)
        return _product(row)

    async def get_product_by_sku(self, sku: str) -> Product | None:
        row = await self.s.scalar(select(m.Product).where(m.Product.sku == sku.upper()))
        return _product(row)

    async def update_product(self, product_id, data: dict) -> Product | None:
        row = await self.s.get(m.Product, product_id)
        if not row:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        if "name" in data:
            row.name_lower = data["name"].lower()
        await self.s.commit()
        return _product(row)

    async def adjust_stock(self, product_id, delta: int) -> Product | None:
        # Атомарний зсув: без цього два паралельні замовлення могли вигребти
        # той самий залишок і вивести його в мінус.
        await self.s.execute(
            update(m.Product)
            .where(m.Product.id == product_id)
            .values(stock=_not_below_zero(m.Product.stock + delta))
        )
        await self._commit()
        return _product(await self.s.get(m.Product, product_id))

    async def set_stock(self, product_id, stock: int) -> Product | None:
        row = await self.s.get(m.Product, product_id)
        if not row:
            return None
        row.stock = max(0, stock)
        await self.s.commit()
        return _product(row)

    async def count_low_stock(self, threshold=5) -> int:
        return await self.s.scalar(
            select(func.count(m.Product.id))
            .where(m.Product.is_active.is_(True), m.Product.stock < threshold)
        ) or 0

    # ------------------------------------------------------------- cart

    async def get_cart(self, user_id) -> list[CartLine]:
        rows = await self.s.scalars(
            select(m.CartItem).where(m.CartItem.user_id == user_id)
            .options(selectinload(m.CartItem.product)).order_by(m.CartItem.id)
        )
        return [CartLine(product_id=r.product_id, qty=r.qty, product=_product(r.product))
                for r in rows]

    async def set_cart_qty(self, user_id, product_id, qty: int) -> None:
        row = await self.s.scalar(
            select(m.CartItem).where(
                m.CartItem.user_id == user_id, m.CartItem.product_id == product_id
            )
        )
        if qty <= 0:
            if row:
                await self.s.delete(row)
                await self.s.commit()
            return
        if row:
            row.qty = qty
        else:
            self.s.add(m.CartItem(user_id=user_id, product_id=product_id, qty=qty))
        await self.s.commit()

    async def clear_cart(self, user_id) -> None:
        await self.s.execute(delete(m.CartItem).where(m.CartItem.user_id == user_id))
        await self._commit()

    # ----------------------------------------------------------- orders

    async def create_order(self, order: Order, lines: list[OrderLine]) -> Order:
        row = m.Order(
            user_id=order.user_id, subtotal=order.subtotal, discount=order.discount,
            bonus_used=order.bonus_used, total=order.total,
            promo_code_id=order.promo_code_id, payment_method=order.payment_method,
            contact_name=order.contact_name, contact_phone=order.contact_phone,
            delivery_city=order.delivery_city, delivery_address=order.delivery_address,
            delivery_method=order.delivery_method,
            delivery_city_ref=order.delivery_city_ref,
            delivery_warehouse_ref=order.delivery_warehouse_ref,
            comment=order.comment,
            search_key=f"{order.contact_name or ''} {order.contact_phone or ''}".lower(),
        )
        self.s.add(row)
        await self.s.flush()
        for line in lines:
            self.s.add(m.OrderItem(
                order_id=row.id, product_id=line.product_id,
                name=line.name, price=line.price, qty=line.qty,
            ))
        await self.s.commit()
        loaded = await self.s.scalar(
            select(m.Order).where(m.Order.id == row.id).options(selectinload(m.Order.items))
        )
        return _order(loaded)

    async def get_order(self, order_id) -> Order | None:
        row = await self.s.scalar(
            select(m.Order).where(m.Order.id == order_id)
            .options(selectinload(m.Order.items), selectinload(m.Order.user))
        )
        return _order(row, with_user=True)

    async def list_orders(self, status=None, search=None, user_id=None,
                          date_from=None, date_to=None, limit=100, offset=0,
                          crm_status_id=None, legacy_only=False):
        query = (
            select(m.Order)
            .options(selectinload(m.Order.items), selectinload(m.Order.user))
            .order_by(m.Order.created_at.desc()).limit(limit).offset(offset)
        )
        if status:
            query = query.where(m.Order.status == status)
        if crm_status_id is not None:
            query = query.where(m.Order.crm_id.is_not(None), m.Order.crm_status_id == str(crm_status_id))
        if legacy_only:
            query = query.where(m.Order.crm_id.is_(None))
        if user_id:
            query = query.where(m.Order.user_id == user_id)
        if search:
            query = query.where(m.Order.search_key.like(f"%{search.lower()}%"))
        if date_from:
            query = query.where(m.Order.created_at >= _day_start(date_from))
        if date_to:
            # Кінець доби включно: інакше фільтр «по сьогодні» відкидав би
            # усе, що оформили сьогодні після півночі
            query = query.where(m.Order.created_at < _day_end(date_to))
        return [_order(r, with_user=True) for r in await self.s.scalars(query)]

    async def update_order(self, order_id, data: dict) -> Order | None:
        row = await self.s.scalar(
            select(m.Order).where(m.Order.id == order_id)
            .options(selectinload(m.Order.items), selectinload(m.Order.user))
        )
        if not row:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.s.commit()
        return _order(row, with_user=True)

    async def find_order_by_crm_id(self, crm_id: str) -> Order | None:
        row = await self.s.scalar(
            select(m.Order).where(m.Order.crm_id == str(crm_id))
            .options(selectinload(m.Order.items), selectinload(m.Order.user))
        )
        return _order(row, with_user=True)

    async def orders_for_crm_sync(self, states, limit: int = 50) -> list[Order]:
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import and_, or_
        states = list(states)
        # «creating» свіжий — означає, що відправка саме йде в процесі API.
        # Узяти його зараз означало б створити дубль заявки. Старший за
        # десять хвилин — процес упав посеред запиту, і стан невідомий.
        stale = datetime.now(timezone.utc) - timedelta(minutes=10)
        plain = [s for s in states if s != "creating"]
        condition = m.Order.crm_state.in_(plain)
        if "creating" in states:
            condition = or_(condition, and_(m.Order.crm_state == "creating",
                                            m.Order.updated_at < stale))
        rows = await self.s.scalars(
            select(m.Order).where(condition)
            .options(selectinload(m.Order.items), selectinload(m.Order.user))
            .order_by(m.Order.id).limit(limit)
        )
        return [_order(r, with_user=True) for r in rows]

    async def count_orders(self, status=None) -> int:
        query = select(func.count(m.Order.id))
        if status:
            query = query.where(m.Order.status == status)
        return await self.s.scalar(query) or 0

    async def status_breakdown(self) -> dict[str, int]:
        rows = await self.s.execute(
            select(m.Order.status, func.count(m.Order.id)).group_by(m.Order.status)
        )
        return {status.value: count for status, count in rows}

    async def display_status_breakdown(
        self, *, since: datetime | None = None, until: datetime | None = None,
    ) -> list[dict]:
        """Групування для панелі без змішування local status із SalesDrive.

        Якщо передані межі, розріз відповідає тому самому періоду, що й решта
        сторінки статистики. Раніше статуси завжди були «за весь час», навіть
        коли зверху обирали «Сьогодні» — числа в одному екрані суперечили одне
        одному.
        """
        crm_query = (
            select(m.Order.crm_status_id, func.max(m.Order.crm_status_name), func.count(m.Order.id))
            .where(m.Order.crm_id.is_not(None))
        )
        legacy_query = (
            select(m.Order.status, func.count(m.Order.id))
            .where(m.Order.crm_id.is_(None))
        )
        if since is not None:
            crm_query = crm_query.where(m.Order.created_at >= since)
            legacy_query = legacy_query.where(m.Order.created_at >= since)
        if until is not None:
            crm_query = crm_query.where(m.Order.created_at < until)
            legacy_query = legacy_query.where(m.Order.created_at < until)
        crm_rows = await self.s.execute(crm_query.group_by(m.Order.crm_status_id))
        legacy_rows = await self.s.execute(legacy_query.group_by(m.Order.status))
        result = [
            {
                "source": "crm",
                "status": str(status_id or ""),
                "name": str(status_name or "").strip(),
                "count": int(count),
            }
            for status_id, status_name, count in crm_rows
        ]
        result.extend(
            {"source": "legacy", "status": status.value, "name": "", "count": int(count)}
            for status, count in legacy_rows
        )
        return result

    # ----------------------------------------------------------- promos

    async def get_promo_by_code(self, code: str) -> Promo | None:
        return _promo(await self.s.scalar(
            select(m.PromoCode).where(func.upper(m.PromoCode.code) == code.strip().upper())
        ))

    async def get_promo(self, promo_id) -> Promo | None:
        return _promo(await self.s.get(m.PromoCode, promo_id))

    async def list_promos(self) -> list[Promo]:
        return [_promo(r) for r in await self.s.scalars(
            select(m.PromoCode).order_by(m.PromoCode.created_at.desc())
        )]

    async def create_promo(self, data: dict) -> Promo:
        row = m.PromoCode(**data)
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)
        return _promo(row)

    async def update_promo(self, promo_id, data: dict) -> Promo | None:
        row = await self.s.get(m.PromoCode, promo_id)
        if not row:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.s.commit()
        return _promo(row)

    async def promo_uses_by_user(self, promo_id, user_id) -> int:
        return await self.s.scalar(
            select(func.count(m.PromoUsage.id)).where(
                m.PromoUsage.promo_id == promo_id, m.PromoUsage.user_id == user_id
            )
        ) or 0

    async def register_promo_use(self, promo_id, user_id, order_id) -> None:
        self.s.add(m.PromoUsage(promo_id=promo_id, user_id=user_id, order_id=order_id))
        await self.s.execute(
            update(m.PromoCode).where(m.PromoCode.id == promo_id)
            .values(used_count=m.PromoCode.used_count + 1)
        )
        await self._commit()

    # ------------------------------------------------------- broadcasts

    async def list_broadcasts(self) -> list[Broadcast]:
        return [_broadcast(r) for r in await self.s.scalars(
            select(m.Broadcast).order_by(m.Broadcast.created_at.desc())
        )]

    async def get_broadcast(self, broadcast_id) -> Broadcast | None:
        return _broadcast(await self.s.get(m.Broadcast, broadcast_id))

    async def create_broadcast(self, data: dict) -> Broadcast:
        row = m.Broadcast(**data)
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)
        return _broadcast(row)

    async def update_broadcast(self, broadcast_id, data: dict) -> Broadcast | None:
        row = await self.s.get(m.Broadcast, broadcast_id)
        if not row:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.s.commit()
        return _broadcast(row)

    async def delete_order(self, order_id) -> bool:
        # Позиції й повідомлення прибираємо явно, а не покладаємось на
        # каскад: він налаштований не на всіх звʼязках, і мовчазні сироти
        # в базі гірші за зайвий запит.
        await self.s.execute(delete(m.OrderItem).where(m.OrderItem.order_id == order_id))
        await self.s.execute(
            delete(m.OrderMessage).where(m.OrderMessage.order_id == order_id))
        await self._delete_panel_notifications_for_entity(
            ("order.created", "order.message"), order_id
        )
        result = await self.s.execute(delete(m.Order).where(m.Order.id == order_id))
        await self.s.commit()
        return result.rowcount > 0

    async def delete_all_orders(self) -> int:
        count = (await self.s.execute(select(func.count()).select_from(m.Order))).scalar_one()
        await self.s.execute(delete(m.OrderItem))
        await self.s.execute(delete(m.OrderMessage))
        notification_ids = list(await self.s.scalars(
            select(m.PanelNotification.id).where(
                m.PanelNotification.kind.in_(("order.created", "order.message"))
            )
        ))
        if notification_ids:
            await self.s.execute(
                delete(m.PanelNotificationRead).where(
                    m.PanelNotificationRead.notification_id.in_(notification_ids)
                )
            )
            await self.s.execute(
                delete(m.PanelNotification).where(m.PanelNotification.id.in_(notification_ids))
            )
        await self.s.execute(delete(m.Order))
        # Підсумки клієнтів обнуляємо разом із замовленнями: інакше в
        # картці клієнта лишиться «12 замовлень», яких більше немає.
        await self.s.execute(update(m.User).values(orders_count=0, total_spent=0))
        await self.s.commit()
        return int(count)

    async def delete_broadcast(self, broadcast_id) -> bool:
        row = await self.s.get(m.Broadcast, broadcast_id)
        if not row:
            return False
        await self.s.delete(row)
        await self.s.commit()
        return True

    async def next_pending_broadcast(self) -> Broadcast | None:
        return _broadcast(await self.s.scalar(
            select(m.Broadcast).where(m.Broadcast.status == BroadcastStatus.SENDING)
            .order_by(m.Broadcast.created_at).limit(1)
        ))

    async def due_broadcasts(self, now: datetime) -> list[Broadcast]:
        """Заплановані розсилки, чий час уже настав.

        Беремо всі дозрілі, а не одну: якщо планувальник стояв (рестарт
        сервера, збій), пропущені розсилки мають піти після відновлення,
        а не загубитися до наступного збігу хвилини.
        """
        rows = await self.s.scalars(
            select(m.Broadcast)
            .where(
                m.Broadcast.status == BroadcastStatus.SCHEDULED,
                m.Broadcast.scheduled_at.is_not(None),
                m.Broadcast.scheduled_at <= now,
            )
            .order_by(m.Broadcast.scheduled_at)
        )
        return [_broadcast(row) for row in rows]

    # --------------------------------------------------------- segments

    def _segment_query(self, segment: dict):
        stype = (segment or {}).get("type", "all")
        base = select(m.User).where(
            m.User.is_blocked.is_(False), m.User.age_confirmed.is_(True)
        )
        if stype == "with_orders":
            return base.where(m.User.orders_count > 0)
        if stype == "no_orders":
            return base.where(m.User.orders_count == 0)
        if stype == "inactive":
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(segment.get("days", 30)))
            return base.where(m.User.last_seen_at < cutoff)
        if stype == "top_spenders":
            return base.where(m.User.total_spent >= float(segment.get("min_total", 1000)))
        if stype == "with_referrals":
            return base.where(m.User.referrals_count > 0)
        return base

    async def count_segment(self, segment: dict) -> int:
        query = self._segment_query(segment).with_only_columns(
            func.count(m.User.id)
        ).order_by(None)
        return await self.s.scalar(query) or 0

    async def segment_recipients(self, segment, cursor_id, limit):
        query = (
            self._segment_query(segment)
            .with_only_columns(m.User.id, m.User.tg_id)
            .where(m.User.id > cursor_id).order_by(m.User.id).limit(limit)
        )
        return [(row[0], row[1]) for row in await self.s.execute(query)]

    # ------------------------------------------------------------ stats

    async def stats_summary(
        self, days: int, *, since: datetime | None = None, until: datetime | None = None,
    ) -> Stats:
        """Фінансове зведення з розділенням обороту, отриманих і очікуваних коштів.

        ``created_at`` визначає, до якого періоду належить замовлення. Межі
        календарних періодів (сьогодні/місяць) рахує router у часовій зоні
        магазину і передає сюди UTC-моменти. Прямі виклики зі старих тестів
        зберігають колишню поведінку rolling-N-days.
        """
        now = datetime.now(timezone.utc)
        period_since = since or (
            now - timedelta(days=days) if days > 0 else datetime.fromtimestamp(0, tz=timezone.utc)
        )
        period_until = until or now

        rows = list((await self.s.execute(
            select(
                m.Order.status, m.Order.payment_method, m.Order.total,
                m.Order.crm_snapshot, m.Order.created_at, m.Order.user_id,
            ).where(m.Order.status.in_(CONFIRMED_SQL))
        )).all())

        confirmed_total = received_total = expected_total = Decimal(0)
        shipped_total = actual_total = calculated_total = Decimal(0)
        confirmed_period = received_period = expected_period = Decimal(0)
        shipped_period = actual_period = calculated_period = Decimal(0)
        confirmed_count = received_count = 0
        confirmed_period_count = received_period_count = shipped_period_count = 0
        buyers_period: set[int] = set()

        for row in rows:
            fin = stats_finance_values(row.status, _stats_payment_method(row, row.crm_snapshot or {}), row.total, row.crm_snapshot)
            confirmed_total += fin["total"]
            received_total += fin["received"]
            expected_total += fin["expected"]
            actual_total += fin["actual_received"]
            calculated_total += fin["calculated_received"]
            confirmed_count += 1
            if fin["received"] > 0:
                received_count += 1
            if fin["shipped"]:
                shipped_total += fin["total"]

            if _in_window(row.created_at, period_since, period_until):
                confirmed_period += fin["total"]
                received_period += fin["received"]
                expected_period += fin["expected"]
                actual_period += fin["actual_received"]
                calculated_period += fin["calculated_received"]
                confirmed_period_count += 1
                buyers_period.add(int(row.user_id))
                if fin["received"] > 0:
                    received_period_count += 1
                if fin["shipped"]:
                    shipped_period += fin["total"]
                    shipped_period_count += 1

        active_24h_since = now - timedelta(hours=24)
        customers_total = await self.s.scalar(select(func.count(m.User.id))) or 0
        customers_period = await self.s.scalar(
            select(func.count(m.User.id)).where(
                m.User.created_at >= period_since, m.User.created_at < period_until
            )
        ) or 0
        active_users_period = await self.s.scalar(
            select(func.count(m.User.id)).where(
                m.User.last_seen_at >= period_since, m.User.last_seen_at < period_until
            )
        ) or 0
        active_users_24h = await self.s.scalar(
            select(func.count(m.User.id)).where(m.User.last_seen_at >= active_24h_since)
        ) or 0

        return Stats(
            # Backward-compatible revenue = гроші, які вже вважаємо отриманими.
            revenue_total=received_total,
            revenue_period=received_period,
            confirmed_total=confirmed_total,
            confirmed_period=confirmed_period,
            shipped_total=shipped_total,
            shipped_period=shipped_period,
            expected_total=expected_total,
            expected_period=expected_period,
            actual_received_total=actual_total,
            actual_received_period=actual_period,
            calculated_received_total=calculated_total,
            calculated_received_period=calculated_period,
            orders_total=await self.count_orders(),
            orders_new=await self.count_orders(OrderStatus.NEW),
            customers_total=customers_total,
            customers_period=customers_period,
            active_users_period=int(active_users_period),
            active_users_24h=int(active_users_24h),
            buyers_period=len(buyers_period),
            avg_check=(confirmed_total / confirmed_count).quantize(Decimal("0.01"))
            if confirmed_count else Decimal(0),
            avg_check_period=(confirmed_period / confirmed_period_count).quantize(Decimal("0.01"))
            if confirmed_period_count else Decimal(0),
            # Старе поле лишається кількістю замовлень із уже отриманою сумою.
            orders_period=received_period_count,
            confirmed_orders_period=confirmed_period_count,
            shipped_orders_period=shipped_period_count,
            low_stock=await self.count_low_stock(),
        )

    async def stats_insights(
        self, days: int, *, since: datetime | None = None, until: datetime | None = None,
        previous_since: datetime | None = None, tz=None,
    ) -> dict:
        """Порівняння, активність користувачів і поведінка підтверджених продажів."""
        now = datetime.now(timezone.utc)
        span = days if days > 0 else 3650
        period_until = until or now
        period_since = since or (now - timedelta(days=span))
        duration = period_until - period_since
        prev_until = period_since
        prev_since = previous_since if previous_since is not None else period_since - duration
        compare_enabled = since is None or previous_since is not None

        query_since = prev_since if compare_enabled else period_since
        rows = list((await self.s.execute(
            select(
                m.Order.created_at, m.Order.total, m.Order.status,
                m.Order.payment_method, m.Order.delivery_method, m.Order.user_id,
                m.Order.crm_snapshot,
            ).where(m.Order.created_at >= query_since, m.Order.created_at < period_until)
        )).all())

        first_seen = dict((await self.s.execute(
            select(m.Order.user_id, func.min(m.Order.created_at))
            .where(m.Order.status.in_(CONFIRMED_SQL))
            .group_by(m.Order.user_id)
        )).all())

        current = [r for r in rows if _in_window(r.created_at, period_since, period_until)]
        previous = [r for r in rows if compare_enabled and _in_window(r.created_at, prev_since, prev_until)]

        def confirmed_rows(bucket):
            return [(r, stats_finance_values(
                r.status, _stats_payment_method(r, r.crm_snapshot or {}), r.total, r.crm_snapshot
            )) for r in bucket if str(getattr(r.status, "value", r.status)) in CONFIRMED_VALUES]

        current_sales = confirmed_rows(current)
        previous_sales = confirmed_rows(previous)

        def sum_field(bucket, key):
            return sum((fin[key] for _, fin in bucket), Decimal(0))

        turnover = sum_field(current_sales, "total")
        received = sum_field(current_sales, "received")
        expected = sum_field(current_sales, "expected")
        was_turnover = sum_field(previous_sales, "total")
        was_received = sum_field(previous_sales, "received")
        orders = len(current_sales)
        was_orders = len(previous_sales)

        by_hour = [0] * 24
        by_weekday = [0] * 7
        payment = {
            "card": {"orders": 0, "revenue": Decimal(0), "received": Decimal(0), "expected": Decimal(0)},
            "cod": {"orders": 0, "revenue": Decimal(0), "received": Decimal(0), "expected": Decimal(0)},
        }
        delivery = {"warehouse": 0, "courier": 0, "unknown": 0}
        returning_orders = new_orders = 0
        shipped_orders = 0
        shipped_amount = Decimal(0)

        for row, fin in current_sales:
            when = _aware(row.created_at)
            if tz is not None:
                when = when.astimezone(tz)
            by_hour[when.hour] += 1
            by_weekday[when.weekday()] += 1

            method = _stats_payment_method(row, row.crm_snapshot or {})
            slot = payment.get(method)
            if slot is not None:
                slot["orders"] += 1
                slot["revenue"] += fin["total"]
                slot["received"] += fin["received"]
                slot["expected"] += fin["expected"]

            delivery[row.delivery_method if row.delivery_method in delivery else "unknown"] += 1
            if fin["shipped"]:
                shipped_orders += 1
                shipped_amount += fin["total"]

            earliest = first_seen.get(row.user_id)
            if earliest is not None and _aware(earliest) < _aware(row.created_at):
                returning_orders += 1
            else:
                new_orders += 1

        cancelled = [r for r in current if r.status == OrderStatus.CANCELLED]
        created_in_period = len(current)
        active_users = await self.s.scalar(
            select(func.count(m.User.id)).where(
                m.User.last_seen_at >= period_since, m.User.last_seen_at < period_until
            )
        ) or 0
        new_users = await self.s.scalar(
            select(func.count(m.User.id)).where(
                m.User.created_at >= period_since, m.User.created_at < period_until
            )
        ) or 0
        active_24h = await self.s.scalar(
            select(func.count(m.User.id)).where(m.User.last_seen_at >= now - timedelta(hours=24))
        ) or 0
        unique_buyers = len({int(r.user_id) for r, _ in current_sales})

        return {
            "days": span,
            "timezone": str(getattr(tz, "key", tz) or "UTC"),
            "period": {
                "from": period_since.isoformat(), "to": period_until.isoformat(),
            },
            "revenue": {
                "value": float(received), "was": float(was_received),
                "change": _change(received, was_received) if compare_enabled else None,
            },
            "turnover": {
                "value": float(turnover), "was": float(was_turnover),
                "change": _change(turnover, was_turnover) if compare_enabled else None,
            },
            "expected": {"value": float(expected)},
            "orders": {
                "value": orders, "was": was_orders,
                "change": _change(Decimal(orders), Decimal(was_orders)) if compare_enabled else None,
            },
            "shipped": {"orders": shipped_orders, "amount": float(shipped_amount)},
            "avg_check": {
                "value": float(turnover / orders) if orders else 0.0,
                "was": float(was_turnover / was_orders) if was_orders else 0.0,
                "change": _change(
                    turnover / orders if orders else Decimal(0),
                    was_turnover / was_orders if was_orders else Decimal(0),
                ) if compare_enabled else None,
            },
            "repeat": {
                "new_orders": new_orders,
                "returning_orders": returning_orders,
                "share": round(returning_orders * 100 / orders, 1) if orders else 0.0,
            },
            "cancelled": {
                "orders": len(cancelled),
                "lost": float(sum((_dec(r.total) for r in cancelled), Decimal(0))),
                "share": round(len(cancelled) * 100 / created_in_period, 1)
                if created_in_period else 0.0,
            },
            "payment": {
                key: {
                    "orders": slot["orders"],
                    "revenue": float(slot["revenue"]),
                    "received": float(slot["received"]),
                    "expected": float(slot["expected"]),
                } for key, slot in payment.items()
            },
            "delivery": delivery,
            "activity": {
                "active_users": int(active_users),
                "active_24h": int(active_24h),
                "new_users": int(new_users),
                "buyers": unique_buyers,
                "buyer_share": round(unique_buyers * 100 / active_users, 1) if active_users else 0.0,
            },
            "by_hour": by_hour,
            "by_weekday": by_weekday,
        }

    async def stats_by_operator(
        self, days: int, *, since: datetime | None = None, until: datetime | None = None,
    ) -> list[dict]:
        now = datetime.now(timezone.utc)
        period_since = since or (
            now - timedelta(days=days) if days > 0 else datetime.fromtimestamp(0, tz=timezone.utc)
        )
        period_until = until or now
        rows = list((await self.s.execute(
            select(
                m.Order.operator_name, m.Order.status, m.Order.payment_method,
                m.Order.total, m.Order.crm_snapshot, m.Order.created_at,
            ).where(
                m.Order.status.in_(CONFIRMED_SQL),
                m.Order.created_at >= period_since, m.Order.created_at < period_until,
            )
        )).all())
        grouped: dict[str, dict] = {}
        for row in rows:
            name = row.operator_name or "Без менеджера"
            fin = stats_finance_values(
                row.status, _stats_payment_method(row, row.crm_snapshot or {}), row.total, row.crm_snapshot
            )
            slot = grouped.setdefault(name, {
                "operator_name": name, "orders": 0, "revenue": Decimal(0),
                "received": Decimal(0), "expected": Decimal(0),
            })
            slot["orders"] += 1
            slot["revenue"] += fin["total"]
            slot["received"] += fin["received"]
            slot["expected"] += fin["expected"]
        result = []
        for slot in grouped.values():
            slot["avg_check"] = (slot["revenue"] / slot["orders"]).quantize(Decimal("0.01")) if slot["orders"] else Decimal(0)
            result.append(slot)
        result.sort(key=lambda item: item["revenue"], reverse=True)
        return result

    async def stats_series(
        self, days: int, *, since: datetime | None = None, until: datetime | None = None, tz=None,
    ) -> list[dict]:
        now = datetime.now(timezone.utc)
        period_since = since or (now - timedelta(days=days))
        period_until = until or now
        rows = list((await self.s.execute(
            select(
                m.Order.created_at, m.Order.total, m.Order.status,
                m.Order.payment_method, m.Order.crm_snapshot,
            ).where(
                m.Order.status.in_(CONFIRMED_SQL),
                m.Order.created_at >= period_since, m.Order.created_at < period_until,
            )
        )).all())
        buckets: dict[str, dict] = {}
        for row in rows:
            moment = _aware(row.created_at)
            if tz is not None:
                moment = moment.astimezone(tz)
            key = moment.strftime("%Y-%m-%d")
            bucket = buckets.setdefault(key, {
                "date": key, "revenue": Decimal(0), "confirmed": Decimal(0),
                "expected": Decimal(0), "orders": 0, "shipped": 0,
            })
            fin = stats_finance_values(
                row.status, _stats_payment_method(row, row.crm_snapshot or {}), row.total, row.crm_snapshot
            )
            bucket["revenue"] += fin["received"]
            bucket["confirmed"] += fin["total"]
            bucket["expected"] += fin["expected"]
            bucket["orders"] += 1
            if fin["shipped"]:
                bucket["shipped"] += 1
        return [buckets[k] for k in sorted(buckets)]

    async def stats_top_products(
        self, days: int, limit: int, *, since: datetime | None = None, until: datetime | None = None,
    ) -> list[dict]:
        now = datetime.now(timezone.utc)
        period_since = since or (
            now - timedelta(days=days) if days > 0 else datetime.fromtimestamp(0, tz=timezone.utc)
        )
        period_until = until or now
        rows = await self.s.execute(
            select(
                m.OrderItem.name,
                func.sum(m.OrderItem.qty),
                func.sum(m.OrderItem.price * m.OrderItem.qty),
            )
            .join(m.Order, m.Order.id == m.OrderItem.order_id)
            .where(
                m.Order.status.in_(CONFIRMED_SQL),
                m.Order.created_at >= period_since, m.Order.created_at < period_until,
            )
            .group_by(m.OrderItem.name)
            .order_by(func.sum(m.OrderItem.price * m.OrderItem.qty).desc())
            .limit(limit)
        )
        return [{"name": n, "qty": int(q), "revenue": _dec(r)} for n, q, r in rows]

    # --------------------------------------------------- налаштування

    async def get_settings_map(self) -> dict[str, str]:
        rows = await self.s.execute(select(m.Setting.key, m.Setting.value))
        return {key: value for key, value in rows}

    async def save_settings_map(self, values: dict[str, str]) -> None:
        existing = {key for (key,) in await self.s.execute(select(m.Setting.key))}
        for key, value in values.items():
            if key in existing:
                await self.s.execute(
                    update(m.Setting).where(m.Setting.key == key).values(value=str(value))
                )
            else:
                self.s.add(m.Setting(key=key, value=str(value)))
        await self._commit()

    # ------------------------------------------ остаточне видалення

    async def _delete_panel_notifications_for_entity(
        self, kinds: tuple[str, ...] | list[str], entity_id: int
    ) -> int:
        """Прибирає оперативні сповіщення разом із видаленим джерелом.

        PanelNotification — не аудит. Якщо товар/замовлення/support-сесію
        стерли, посилання на неіснуючу сутність не повинно висіти в дзвіночку.
        Read-мітки чистимо явно: у Postgres FK має CASCADE, але SQLite у
        частині локальних запусків працює без foreign_keys=ON.
        """
        ids = list(await self.s.scalars(
            select(m.PanelNotification.id).where(
                m.PanelNotification.kind.in_(tuple(kinds)),
                m.PanelNotification.entity_id == int(entity_id),
            )
        ))
        if not ids:
            return 0
        await self.s.execute(
            delete(m.PanelNotificationRead).where(
                m.PanelNotificationRead.notification_id.in_(ids)
            )
        )
        result = await self.s.execute(
            delete(m.PanelNotification).where(m.PanelNotification.id.in_(ids))
        )
        return int(result.rowcount or 0)

    async def _prune_orphan_panel_notifications(self) -> int:
        """Одноразово/ледаче чистить події, джерело яких уже було видалене.

        Це також лікує записи, створені старими версіями до появи cleanup
        у delete/purge-операціях. Викликається лише на повному refresh центру,
        а не на кожному 10-секундному incremental poll.
        """
        removed = 0
        specs = (
            (("order.created", "order.message"), m.Order),
            (("support.message",), m.SupportThread),
            (("product.created",), m.Product),
        )
        for kinds, model in specs:
            ids = list(await self.s.scalars(
                select(m.PanelNotification.id).where(
                    m.PanelNotification.kind.in_(kinds),
                    m.PanelNotification.entity_id.is_not(None),
                    ~m.PanelNotification.entity_id.in_(select(model.id)),
                )
            ))
            if not ids:
                continue
            await self.s.execute(
                delete(m.PanelNotificationRead).where(
                    m.PanelNotificationRead.notification_id.in_(ids)
                )
            )
            result = await self.s.execute(
                delete(m.PanelNotification).where(m.PanelNotification.id.in_(ids))
            )
            removed += int(result.rowcount or 0)
        if removed:
            await self.s.commit()
        return removed

    async def purge_product(self, product_id) -> bool:
        row = await self.s.get(m.Product, product_id)
        if not row:
            return False
        # Знеособлюємо історію явно: покладатись на ON DELETE SET NULL не можна,
        # бо SQLite за замовчуванням не вмикає перевірку зовнішніх ключів.
        await self.s.execute(
            update(m.OrderItem)
            .where(m.OrderItem.product_id == product_id)
            .values(product_id=None)
        )
        await self.s.execute(delete(m.CartItem).where(m.CartItem.product_id == product_id))
        await self._delete_panel_notifications_for_entity(("product.created",), product_id)
        # products_count у SQL — обчислюване поле (COUNT), окремо його не рухаємо
        await self.s.delete(row)
        await self._commit()
        return True

    async def purge_category(self, category_id) -> int:
        if not await self.s.get(m.Category, category_id):
            return 0
        ids = list(
            await self.s.scalars(
                select(m.Product.id).where(m.Product.category_id == category_id)
            )
        )
        for product_id in ids:
            await self.purge_product(product_id)
        row = await self.s.get(m.Category, category_id)
        if row:
            await self.s.delete(row)
            await self.s.commit()
        return len(ids)

    async def purge_promo(self, promo_id) -> bool:
        row = await self.s.get(m.PromoCode, promo_id)
        if not row:
            return False
        # orders.promo_code_id — звичайний FK без ondelete, тож чистимо вручну,
        # інакше Postgres відмовить у видаленні.
        await self.s.execute(
            update(m.Order).where(m.Order.promo_code_id == promo_id).values(promo_code_id=None)
        )
        await self.s.execute(delete(m.PromoUsage).where(m.PromoUsage.promo_id == promo_id))
        await self.s.delete(row)
        await self._commit()
        return True

    # -------------------------------------------------- чат замовлення

    async def set_chat_order(self, user_id, order_id) -> None:
        await self.s.execute(
            update(m.User).where(m.User.id == user_id).values(chat_order_id=order_id)
        )
        await self._commit()

    async def add_order_message(self, data: dict) -> OrderMessage:
        row = m.OrderMessage(**data)
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)
        return _order_message(row)

    async def list_order_messages(
        self, order_id, limit: int = 200, after_id: int | None = None,
    ) -> list[OrderMessage]:
        """Останні повідомлення або інкремент після ``after_id``.

        Старий запит сортував ASC і лише потім застосовував LIMIT 200, тому
        у довгій переписці повертав *найстаріші* 200 повідомлень і нові
        репліки фактично переставали з'являтися в панелі. Початкове читання
        тепер бере останні 200 через DESC + reverse, а live polling тягне
        лише повідомлення з більшим id.
        """
        cap = max(1, min(int(limit or 200), 500))
        if after_id is not None:
            rows = list(await self.s.scalars(
                select(m.OrderMessage)
                .where(
                    m.OrderMessage.order_id == order_id,
                    m.OrderMessage.id > int(after_id),
                )
                .order_by(m.OrderMessage.id)
                .limit(cap)
            ))
            return [_order_message(r) for r in rows]

        rows = list(await self.s.scalars(
            select(m.OrderMessage)
            .where(m.OrderMessage.order_id == order_id)
            .order_by(m.OrderMessage.created_at.desc(), m.OrderMessage.id.desc())
            .limit(cap)
        ))
        rows.reverse()
        return [_order_message(r) for r in rows]

    async def find_order_by_tg_message(self, tg_message_id: int) -> int | None:
        return await self.s.scalar(
            select(m.OrderMessage.order_id).where(m.OrderMessage.tg_message_id == tg_message_id)
        )

    async def mark_messages_read(self, order_id) -> int:
        result = await self.s.execute(
            update(m.OrderMessage)
            .where(
                m.OrderMessage.order_id == order_id,
                m.OrderMessage.direction == "in",
                m.OrderMessage.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await self._commit()
        return int(result.rowcount or 0)

    async def mark_client_read(self, order_id) -> int:
        """Клієнт відкрив стрічку — повідомлення менеджера прочитані.

        Дзеркальне до mark_messages_read, але в інший бік. Раніше
        повідомлення менеджера зберігались одразу як прочитані, тож
        «прочитано» не означало нічого: менеджер не міг відрізнити
        мовчання від «не бачив».
        """
        result = await self.s.execute(
            update(m.OrderMessage)
            .where(
                m.OrderMessage.order_id == order_id,
                m.OrderMessage.direction == "out",
                m.OrderMessage.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await self._commit()
        return int(result.rowcount or 0)

    async def forget_chat_files(self, older_than_days: int) -> int:
        """Забуває коди вкладень виконаних замовлень.

        Часом виконання вважаємо updated_at: окремої позначки «коли
        завершили» в замовленні немає, а updated_at міняється при кожній
        зміні статусу, тож для замовлення, яке вже в «Виконано», це і є
        момент останньої дії з ним. Якщо менеджер потім щось поправить,
        відлік почнеться заново — це радше добре: значить, до замовлення
        ще поверталися.

        Назву файлу лишаємо: у стрічці має бути видно, що вкладення було,
        інакше розмова читається як обірвана.
        """
        edge = datetime.now(timezone.utc) - timedelta(days=older_than_days)
        stale = (
            select(m.Order.id)
            .where(m.Order.status == OrderStatus.DONE, m.Order.updated_at < edge)
        )
        result = await self.s.execute(
            update(m.OrderMessage)
            .where(
                m.OrderMessage.order_id.in_(stale),
                m.OrderMessage.file_id.is_not(None),
            )
            .values(file_id=None)
        )

        # Загальна підтримка тепер теж приймає фото й документи. Не можна
        # було додати новий канал вкладень і залишити його поза тією самою
        # політикою зберігання: file_id фактично є ключем доступу до файлу.
        stale_support = (
            select(m.SupportThread.id)
            .where(
                m.SupportThread.status == "closed",
                m.SupportThread.updated_at < edge,
            )
        )
        support_result = await self.s.execute(
            update(m.SupportMessage)
            .where(
                m.SupportMessage.thread_id.in_(stale_support),
                m.SupportMessage.file_id.is_not(None),
            )
            .values(file_id=None)
        )
        await self._commit()
        return int(result.rowcount or 0) + int(support_result.rowcount or 0)

    async def set_bot_reachable(self, tg_id: int, reachable: bool) -> None:
        """Позначає, чи доходять до людини повідомлення бота.

        Пишемо лише при зміні: інакше кожне вдале сповіщення оновлювало б
        рядок користувача й тягло за собою запис у базу на порожньому
        місці.
        """
        await self.s.execute(
            update(m.User)
            .where(m.User.tg_id == tg_id, m.User.bot_reachable.is_(not reachable))
            .values(bot_reachable=reachable)
        )
        await self._commit()

    async def unread_counts(self) -> dict[int, int]:
        rows = await self.s.execute(
            select(m.OrderMessage.order_id, func.count(m.OrderMessage.id))
            .where(m.OrderMessage.direction == "in", m.OrderMessage.is_read.is_(False))
            .group_by(m.OrderMessage.order_id)
        )
        return {order_id: count for order_id, count in rows}

    # ---------------------------------------------------- списки бажаного

    async def list_wishlists(self, user_id) -> list[Wishlist]:
        rows = await self.s.scalars(
            select(m.Wishlist).where(m.Wishlist.user_id == user_id)
            .order_by(m.Wishlist.id)
        )
        return [_wishlist(r) for r in rows]

    async def get_wishlist(self, wishlist_id) -> Wishlist | None:
        return _wishlist(await self.s.get(m.Wishlist, wishlist_id))

    async def create_wishlist(self, user_id, name: str) -> Wishlist:
        row = m.Wishlist(user_id=user_id, name=name, product_ids=[])
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)
        return _wishlist(row)

    async def rename_wishlist(self, wishlist_id, name: str) -> Wishlist | None:
        row = await self.s.get(m.Wishlist, wishlist_id)
        if not row:
            return None
        row.name = name
        await self.s.commit()
        await self.s.refresh(row)
        return _wishlist(row)

    async def delete_wishlist(self, wishlist_id) -> bool:
        row = await self.s.get(m.Wishlist, wishlist_id)
        if not row:
            return False
        await self.s.delete(row)
        await self.s.commit()
        return True

    async def set_wishlist_items(self, wishlist_id, product_ids: list[int]) -> Wishlist | None:
        row = await self.s.get(m.Wishlist, wishlist_id)
        if not row:
            return None
        # Новий список, а не мутація на місці: SQLAlchemy не помічає зміну
        # всередині JSON-колонки й не збереже її
        row.product_ids = list(product_ids)
        await self.s.commit()
        await self.s.refresh(row)
        return _wishlist(row)

    # ------------------------------------------------ загальна підтримка

    async def ensure_support_thread(self, user_id: int) -> SupportThread:
        """Повертає поточну відкриту сесію або створює нову.

        Цей метод викликається тільки явним входом у /ask. Закриті сесії
        не перевідкриваються. Частковий UNIQUE-індекс захищає від двох
        паралельних /ask для одного клієнта.
        """
        row = await self.s.scalar(
            select(m.SupportThread)
            .where(
                m.SupportThread.user_id == user_id,
                m.SupportThread.status == "open",
            )
            .order_by(m.SupportThread.updated_at.desc(), m.SupportThread.id.desc())
        )
        if row is not None:
            return _support_thread(row)

        now = datetime.now(timezone.utc)
        row = m.SupportThread(
            user_id=user_id,
            status="open",
            updated_at=now,
            last_message_at=now,
            closed_at=None,
            closed_by=None,
            closed_by_name=None,
            close_reason=None,
        )
        self.s.add(row)
        try:
            await self.s.commit()
        except IntegrityError:
            # Два /ask могли прийти майже одночасно. База лишає рівно одну
            # відкриту сесію; другий запит після rollback просто бере її.
            await self.s.rollback()
            existing = await self.s.scalar(
                select(m.SupportThread)
                .where(
                    m.SupportThread.user_id == user_id,
                    m.SupportThread.status == "open",
                )
                .order_by(m.SupportThread.updated_at.desc(), m.SupportThread.id.desc())
            )
            if existing is None:
                raise
            return _support_thread(existing)
        await self.s.refresh(row)
        return _support_thread(row)

    async def get_support_thread(self, thread_id: int) -> SupportThread | None:
        row = await self.s.scalar(
            select(m.SupportThread)
            .options(selectinload(m.SupportThread.user))
            .where(m.SupportThread.id == thread_id)
        )
        if not row:
            return None
        unread = await self.s.scalar(
            select(func.count(m.SupportMessage.id)).where(
                m.SupportMessage.thread_id == thread_id,
                m.SupportMessage.direction == "in",
                m.SupportMessage.is_read.is_(False),
            )
        )
        return _support_thread(row, unread_count=int(unread or 0), with_user=True)

    async def get_support_thread_for_user(self, user_id: int) -> SupportThread | None:
        """Повертає тільки активну сесію; закрита ніколи не оживає сама."""
        row = await self.s.scalar(
            select(m.SupportThread)
            .options(selectinload(m.SupportThread.user))
            .where(
                m.SupportThread.user_id == user_id,
                m.SupportThread.status == "open",
            )
            .order_by(m.SupportThread.updated_at.desc(), m.SupportThread.id.desc())
        )
        return _support_thread(row, with_user=True) if row else None

    async def list_support_threads(self, status: str | None = None) -> list[SupportThread]:
        stmt = (
            select(m.SupportThread)
            .options(selectinload(m.SupportThread.user))
            .order_by(
                m.SupportThread.last_message_at.desc().nullslast(),
                m.SupportThread.updated_at.desc(),
                m.SupportThread.id.desc(),
            )
        )
        if status in {"open", "closed"}:
            stmt = stmt.where(m.SupportThread.status == status)
        rows = list(await self.s.scalars(stmt))
        if not rows:
            return []
        ids = [row.id for row in rows]
        counts = {
            int(thread_id): int(count)
            for thread_id, count in (await self.s.execute(
                select(m.SupportMessage.thread_id, func.count(m.SupportMessage.id))
                .where(
                    m.SupportMessage.thread_id.in_(ids),
                    m.SupportMessage.direction == "in",
                    m.SupportMessage.is_read.is_(False),
                )
                .group_by(m.SupportMessage.thread_id)
            )).all()
        }
        return [
            _support_thread(row, unread_count=counts.get(row.id, 0), with_user=True)
            for row in rows
        ]

    async def close_support_thread(
        self,
        thread_id: int,
        *,
        closed_by: str,
        closed_by_name: str = "",
        close_reason: str = "",
    ) -> tuple[SupportThread | None, bool]:
        """Закриває конкретну сесію рівно один раз.

        Рядок блокується до commit. Якщо повідомлення вже почало запис у
        відкриту сесію, воно завершиться перед закриттям; якщо закриття
        виграло гонку — нове повідомлення в цю сесію вже не потрапить.
        """
        row = await self.s.scalar(
            select(m.SupportThread)
            .where(m.SupportThread.id == thread_id)
            .with_for_update()
        )
        if row is None:
            await self.s.commit()
            return None, False
        if row.status == "closed":
            await self.s.commit()
            return await self.get_support_thread(thread_id), False

        now = datetime.now(timezone.utc)
        row.status = "closed"
        row.closed_at = now
        row.closed_by = (closed_by or "system")[:16]
        row.closed_by_name = (closed_by_name or "")[:128] or None
        row.close_reason = (close_reason or "")[:32] or None
        row.updated_at = now
        await self.s.commit()
        return await self.get_support_thread(thread_id), True

    async def add_support_message(self, data: dict) -> SupportMessage:
        """Низькорівнева вставка без перевірки статусу.

        Лишається для міграцій/тестів. Робочі клієнтські та операторські
        повідомлення повинні йти через add_support_message_if_open().
        """
        row = m.SupportMessage(**data)
        self.s.add(row)
        await self.s.flush()
        now = row.created_at or datetime.now(timezone.utc)
        await self.s.execute(
            update(m.SupportThread)
            .where(m.SupportThread.id == row.thread_id)
            .values(last_message_at=now, updated_at=now)
        )
        await self.s.commit()
        await self.s.refresh(row)
        return _support_message(row)

    async def add_support_message_if_open(self, data: dict) -> SupportMessage | None:
        """Атомарно перевіряє сесію й додає повідомлення тільки у open."""
        thread_id = int(data["thread_id"])
        thread = await self.s.scalar(
            select(m.SupportThread)
            .where(
                m.SupportThread.id == thread_id,
                m.SupportThread.status == "open",
            )
            .with_for_update()
        )
        if thread is None:
            await self.s.commit()
            return None

        row = m.SupportMessage(**data)
        self.s.add(row)
        await self.s.flush()
        now = row.created_at or datetime.now(timezone.utc)
        thread.last_message_at = now
        thread.updated_at = now
        await self.s.commit()
        await self.s.refresh(row)
        return _support_message(row)

    async def list_support_messages(self, thread_id: int, limit: int = 300) -> list[SupportMessage]:
        rows = await self.s.scalars(
            select(m.SupportMessage)
            .where(m.SupportMessage.thread_id == thread_id)
            .order_by(m.SupportMessage.created_at, m.SupportMessage.id)
            .limit(limit)
        )
        return [_support_message(row) for row in rows]

    async def mark_support_read(self, thread_id: int) -> int:
        result = await self.s.execute(
            update(m.SupportMessage)
            .where(
                m.SupportMessage.thread_id == thread_id,
                m.SupportMessage.direction == "in",
                m.SupportMessage.is_read.is_(False),
            )
            .values(is_read=True)
        )
        await self._commit()
        return int(result.rowcount or 0)

    async def support_unread_count(self) -> int:
        count = await self.s.scalar(
            select(func.count(m.SupportMessage.id)).where(
                m.SupportMessage.direction == "in",
                m.SupportMessage.is_read.is_(False),
            )
        )
        return int(count or 0)

    async def support_stats(self) -> dict[str, int]:
        open_count = await self.s.scalar(
            select(func.count(m.SupportThread.id)).where(m.SupportThread.status == "open")
        )
        closed_count = await self.s.scalar(
            select(func.count(m.SupportThread.id)).where(m.SupportThread.status == "closed")
        )
        clients = await self.s.scalar(
            select(func.count(func.distinct(m.SupportThread.user_id)))
        )
        unread = await self.support_unread_count()
        return {
            "open": int(open_count or 0),
            "closed": int(closed_count or 0),
            "total": int(open_count or 0) + int(closed_count or 0),
            "clients": int(clients or 0),
            "unread": int(unread or 0),
        }

    async def delete_support_thread(self, thread_id: int) -> bool:
        """Явне ручне видалення. Закриття саме по собі нічого не стирає."""
        row = await self.s.get(m.SupportThread, thread_id)
        if not row:
            return False
        await self._delete_panel_notifications_for_entity(("support.message",), thread_id)
        await self.s.delete(row)
        await self.s.commit()
        return True

    # ----------------------------------------------- центр сповіщень панелі

    @staticmethod
    def _panel_notification_dict(row, *, read: bool = False) -> dict:
        return {
            "id": row.id,
            "kind": row.kind,
            "title": row.title,
            "body": row.body or "",
            "href": row.href,
            "entity_id": row.entity_id,
            "actor": row.actor,
            "created_at": row.created_at,
            "read": bool(read),
        }

    async def create_panel_notification(self, data: dict) -> dict:
        row = m.PanelNotification(**data)
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)

        # Центр сповіщень — оперативний журнал, не архів аудиту. Старші
        # за 90 днів події прибираємо разом із read-мітками через CASCADE,
        # щоб таблиця не росла безмежно роками.
        edge = datetime.now(timezone.utc) - timedelta(days=90)
        await self.s.execute(
            delete(m.PanelNotification).where(m.PanelNotification.created_at < edge)
        )
        await self.s.commit()
        return self._panel_notification_dict(row)

    async def list_panel_notifications(
        self, viewer_key: str, *, limit: int = 60, after_id: int | None = None
    ) -> list[dict]:
        if after_id is None:
            await self._prune_orphan_panel_notifications()
        stmt = select(m.PanelNotification)
        if after_id is not None:
            stmt = stmt.where(m.PanelNotification.id > int(after_id))
        rows = list(await self.s.scalars(
            stmt.order_by(m.PanelNotification.id.desc()).limit(max(1, min(int(limit), 200)))
        ))
        if not rows:
            return []
        ids = [row.id for row in rows]
        read_ids = set(await self.s.scalars(
            select(m.PanelNotificationRead.notification_id).where(
                m.PanelNotificationRead.viewer_key == viewer_key,
                m.PanelNotificationRead.notification_id.in_(ids),
            )
        ))
        return [
            self._panel_notification_dict(row, read=row.id in read_ids)
            for row in rows
        ]

    async def panel_notification_unread_count(self, viewer_key: str) -> int:
        total = int(await self.s.scalar(select(func.count(m.PanelNotification.id))) or 0)
        read = int(await self.s.scalar(
            select(func.count(m.PanelNotificationRead.id)).where(
                m.PanelNotificationRead.viewer_key == viewer_key
            )
        ) or 0)
        return max(0, total - read)

    async def mark_panel_notification_read(self, notification_id: int, viewer_key: str) -> bool:
        exists_row = await self.s.scalar(
            select(m.PanelNotification.id).where(m.PanelNotification.id == notification_id)
        )
        if exists_row is None:
            return False
        already = await self.s.scalar(
            select(m.PanelNotificationRead.id).where(
                m.PanelNotificationRead.notification_id == notification_id,
                m.PanelNotificationRead.viewer_key == viewer_key,
            )
        )
        if already is None:
            self.s.add(m.PanelNotificationRead(
                notification_id=notification_id, viewer_key=viewer_key
            ))
            try:
                await self.s.commit()
            except IntegrityError:
                await self.s.rollback()
        return True

    async def mark_all_panel_notifications_read(self, viewer_key: str) -> int:
        all_ids = set(await self.s.scalars(select(m.PanelNotification.id)))
        if not all_ids:
            return 0
        read_ids = set(await self.s.scalars(
            select(m.PanelNotificationRead.notification_id).where(
                m.PanelNotificationRead.viewer_key == viewer_key
            )
        ))
        pending = sorted(all_ids - read_ids)
        if not pending:
            return 0
        self.s.add_all([
            m.PanelNotificationRead(notification_id=nid, viewer_key=viewer_key)
            for nid in pending
        ])
        await self.s.commit()
        return len(pending)

    # ------------------------------------------------------ менеджери

    async def create_operator(self, data: dict) -> Operator:
        row = m.Operator(**data)
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)
        return _operator(row)

    async def get_operator(self, operator_id) -> Operator | None:
        return _operator(await self.s.get(m.Operator, operator_id))

    async def get_operator_by_login(self, login: str) -> Operator | None:
        row = await self.s.scalar(select(m.Operator).where(m.Operator.login == login))
        return _operator(row)

    async def list_operators(self) -> list[Operator]:
        rows = await self.s.scalars(select(m.Operator).order_by(m.Operator.id))
        return [_operator(r) for r in rows]

    async def update_operator(self, operator_id, data: dict) -> Operator | None:
        row = await self.s.get(m.Operator, operator_id)
        if not row:
            return None
        for key, value in data.items():
            setattr(row, key, value)
        await self.s.commit()
        await self.s.refresh(row)
        return _operator(row)

    async def purge_operator(self, operator_id) -> bool:
        row = await self.s.get(m.Operator, operator_id)
        if not row:
            return False
        # Імʼя в замовленні — знімок, воно лишається; прибираємо тільки звʼязок
        await self.s.execute(
            update(m.Order).where(m.Order.operator_id == operator_id)
            .values(operator_id=None)
        )
        await self.s.delete(row)
        await self._commit()
        return True

    async def delete_operator(self, operator_id) -> bool:
        row = await self.s.get(m.Operator, operator_id)
        if not row:
            return False
        row.is_active = False
        await self.s.commit()
        return True


def _operator(row) -> Operator | None:
    if row is None:
        return None
    return Operator(
        id=row.id, login=row.login, name=row.name or "",
        role=OperatorRole(row.role), is_active=row.is_active,
        created_at=row.created_at, last_login_at=row.last_login_at,
        password_hash=row.password_hash,
    )


def _order_message(row) -> OrderMessage:
    return OrderMessage(
        id=row.id, order_id=row.order_id, user_id=row.user_id,
        direction=row.direction, author=row.author or "", text=row.text,
        tg_message_id=row.tg_message_id, is_read=row.is_read, created_at=row.created_at,
        file_id=row.file_id, file_kind=row.file_kind, file_name=row.file_name,
    )


def _day_start(value: str) -> datetime:
    return datetime.fromisoformat(str(value)[:10]).replace(tzinfo=timezone.utc)


def _day_end(value: str) -> datetime:
    return _day_start(value) + timedelta(days=1)

def _support_message(row) -> SupportMessage:
    return SupportMessage(
        id=row.id, thread_id=row.thread_id, user_id=row.user_id,
        direction=row.direction, author=row.author or "", text=row.text,
        tg_message_id=row.tg_message_id, file_id=row.file_id,
        file_kind=row.file_kind, file_name=row.file_name,
        is_read=row.is_read, is_automatic=bool(getattr(row, "is_automatic", False)),
        created_at=row.created_at,
    )


def _support_thread(row, *, unread_count: int = 0, with_user: bool = False) -> SupportThread | None:
    if row is None:
        return None
    return SupportThread(
        id=row.id, user_id=row.user_id, status=row.status,
        created_at=row.created_at, updated_at=row.updated_at,
        last_message_at=row.last_message_at,
        closed_at=row.closed_at, closed_by=row.closed_by,
        closed_by_name=row.closed_by_name, close_reason=row.close_reason,
        user=_user(row.user) if with_user and row.user else None,
        unread_count=int(unread_count or 0),
    )


def _wishlist(row) -> Wishlist | None:
    if row is None:
        return None
    return Wishlist(
        id=row.id, user_id=row.user_id, name=row.name,
        product_ids=list(row.product_ids or []), created_at=row.created_at,
    )
