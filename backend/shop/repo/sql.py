"""Репозиторій поверх SQLAlchemy — для власного сервера."""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shop import models as m
from shop.entities import (
    Operator, OperatorRole, OrderMessage, SupportMessage, SupportThread, Wishlist, operator_stats_rows,
    PAID_STATUSES, Broadcast, BroadcastStatus, CartLine, Category, Order,
    OrderLine, OrderStatus, Product, Promo, Stats, User,
)
from shop.repo.base import Repository

ALPHABET = string.ascii_uppercase + string.digits
PAID_SQL = [OrderStatus(s.value) for s in PAID_STATUSES]


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
        id=row.id, category_id=row.category_id, name=row.name,
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
            query = query.where(m.Product.name_lower.like(f"%{search.lower()}%"))
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
        data["name_lower"] = data["name"].lower()
        row = m.Product(**data)
        self.s.add(row)
        await self.s.commit()
        await self.s.refresh(row)
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
                          date_from=None, date_to=None, limit=100, offset=0):
        query = (
            select(m.Order)
            .options(selectinload(m.Order.items), selectinload(m.Order.user))
            .order_by(m.Order.created_at.desc()).limit(limit).offset(offset)
        )
        if status:
            query = query.where(m.Order.status == status)
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
        result = await self.s.execute(delete(m.Order).where(m.Order.id == order_id))
        await self.s.commit()
        return result.rowcount > 0

    async def delete_all_orders(self) -> int:
        count = (await self.s.execute(select(func.count()).select_from(m.Order))).scalar_one()
        await self.s.execute(delete(m.OrderItem))
        await self.s.execute(delete(m.OrderMessage))
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

    async def stats_summary(self, days: int) -> Stats:
        # days <= 0 означає «за весь час»: без цього не було б як подивитись
        # підсумок магазину, лише останні N днів
        since = (
            datetime.now(timezone.utc) - timedelta(days=days)
            if days > 0 else datetime.fromtimestamp(0, tz=timezone.utc)
        )
        paid = m.Order.status.in_(PAID_SQL)

        revenue_total = await self.s.scalar(
            select(func.coalesce(func.sum(m.Order.total), 0)).where(paid))
        revenue_period = await self.s.scalar(
            select(func.coalesce(func.sum(m.Order.total), 0))
            .where(paid, m.Order.created_at >= since))
        paid_count = await self.s.scalar(select(func.count(m.Order.id)).where(paid)) or 0
        period_count = await self.s.scalar(
            select(func.count(m.Order.id)).where(paid, m.Order.created_at >= since)) or 0

        return Stats(
            revenue_total=_dec(revenue_total),
            revenue_period=_dec(revenue_period),
            orders_total=await self.count_orders(),
            orders_new=await self.count_orders(OrderStatus.NEW),
            customers_total=await self.s.scalar(select(func.count(m.User.id))) or 0,
            customers_period=await self.s.scalar(
                select(func.count(m.User.id)).where(m.User.created_at >= since)) or 0,
            avg_check=(_dec(revenue_total) / paid_count).quantize(Decimal("0.01"))
            if paid_count else Decimal(0),
            avg_check_period=(_dec(revenue_period) / period_count).quantize(Decimal("0.01"))
            if period_count else Decimal(0),
            orders_period=period_count,
            low_stock=await self.count_low_stock(),
        )

    async def stats_insights(self, days: int) -> dict:
        """Показники, які міняють рішення.

        Рахуємо в Python, а не в SQL, свідомо. Потрібні розрізи — година
        доби, день тижня, «перше замовлення чи ні» — у SQLite і Postgres
        пишуться по-різному, і кожен такий вираз довелося б тримати у
        двох варіантах. Обсяг тут малий: два періоди замовлень магазину,
        а не таблиця подій.
        """
        now = datetime.now(timezone.utc)
        span = days if days > 0 else 3650
        since = now - timedelta(days=span)
        previous_since = since - timedelta(days=span)

        rows = (await self.s.execute(
            select(
                m.Order.created_at, m.Order.total, m.Order.status,
                m.Order.payment_method, m.Order.delivery_method, m.Order.user_id,
            ).where(m.Order.created_at >= previous_since)
        )).all()

        # Дата першого оплаченого замовлення кожного покупця — щоб
        # відрізнити нового від того, хто повернувся. Саме повернення, а
        # не кількість замовлень, показує, чи вартий магазин другого разу.
        first_seen = dict((await self.s.execute(
            select(m.Order.user_id, func.min(m.Order.created_at))
            .where(m.Order.status.in_(PAID_SQL))
            .group_by(m.Order.user_id)
        )).all())

        paid = {status for status in PAID_SQL}

        def moment(value: datetime) -> datetime:
            """Час у UTC, навіть якщо база віддала його без зони.

            SQLite зберігає datetime без зони, Postgres — із зоною. Порівняння
            наївного часу з часом у зоні падає, і це видно лише на одному з
            двох рушіїв — тобто в проді, а не в перевірках.
            """
            return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

        now_window, past_window = [], []
        for row in rows:
            (now_window if moment(row.created_at) >= since else past_window).append(row)

        def money(bucket):
            return sum((_dec(r.total) for r in bucket if r.status in paid), Decimal(0))

        def count(bucket):
            return sum(1 for r in bucket if r.status in paid)

        revenue, orders = money(now_window), count(now_window)
        was_revenue, was_orders = money(past_window), count(past_window)

        by_hour = [0] * 24
        by_weekday = [0] * 7
        payment = {"card": {"orders": 0, "revenue": Decimal(0)},
                   "cod": {"orders": 0, "revenue": Decimal(0)}}
        delivery = {"warehouse": 0, "courier": 0, "unknown": 0}
        returning_orders, new_orders = 0, 0

        for row in now_window:
            if row.status not in paid:
                continue
            when = moment(row.created_at)
            by_hour[when.hour] += 1
            by_weekday[when.weekday()] += 1

            slot = payment.get(row.payment_method or "")
            if slot is not None:
                slot["orders"] += 1
                slot["revenue"] += _dec(row.total)

            delivery[row.delivery_method if row.delivery_method in delivery else "unknown"] += 1

            earliest = first_seen.get(row.user_id)
            if earliest is not None and moment(earliest) < when:
                returning_orders += 1
            else:
                new_orders += 1

        cancelled = [r for r in now_window if r.status == OrderStatus.CANCELLED]
        created_in_period = len(now_window)

        return {
            "days": span,
            "revenue": {
                "value": float(revenue), "was": float(was_revenue),
                "change": _change(revenue, was_revenue),
            },
            "orders": {
                "value": orders, "was": was_orders,
                "change": _change(Decimal(orders), Decimal(was_orders)),
            },
            "avg_check": {
                "value": float(revenue / orders) if orders else 0.0,
                "was": float(was_revenue / was_orders) if was_orders else 0.0,
                "change": _change(
                    revenue / orders if orders else Decimal(0),
                    was_revenue / was_orders if was_orders else Decimal(0),
                ),
            },
            # Повторні — головний показник здоров'я магазину: приплив
            # нових можна купити рекламою, повернення — ні.
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
                key: {"orders": slot["orders"], "revenue": float(slot["revenue"])}
                for key, slot in payment.items()
            },
            "delivery": delivery,
            "by_hour": by_hour,
            "by_weekday": by_weekday,
        }

    async def stats_by_operator(self, days: int) -> list[dict]:
        since = (
            datetime.now(timezone.utc) - timedelta(days=days)
            if days > 0 else datetime.fromtimestamp(0, tz=timezone.utc)
        )
        rows = await self.s.execute(
            select(
                m.Order.operator_name,
                func.count(m.Order.id),
                func.coalesce(func.sum(m.Order.total), 0),
            )
            .where(m.Order.status.in_(PAID_SQL), m.Order.created_at >= since)
            .group_by(m.Order.operator_name)
        )
        return operator_stats_rows([
            (name or "", count, _dec(revenue)) for name, count, revenue in rows
        ])

    async def stats_series(self, days: int) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = await self.s.execute(
            select(m.Order.created_at, m.Order.total)
            .where(m.Order.status.in_(PAID_SQL), m.Order.created_at >= since)
        )
        buckets: dict[str, dict] = {}
        for created_at, total in rows:
            key = created_at.strftime("%Y-%m-%d")
            bucket = buckets.setdefault(key, {"date": key, "revenue": Decimal(0), "orders": 0})
            bucket["revenue"] += _dec(total)
            bucket["orders"] += 1
        return [buckets[k] for k in sorted(buckets)]

    async def stats_top_products(self, days: int, limit: int) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        rows = await self.s.execute(
            select(
                m.OrderItem.name,
                func.sum(m.OrderItem.qty),
                func.sum(m.OrderItem.price * m.OrderItem.qty),
            )
            .join(m.Order, m.Order.id == m.OrderItem.order_id)
            .where(m.Order.status.in_(PAID_SQL), m.Order.created_at >= since)
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

    async def list_order_messages(self, order_id, limit: int = 200) -> list[OrderMessage]:
        rows = await self.s.scalars(
            select(m.OrderMessage)
            .where(m.OrderMessage.order_id == order_id)
            .order_by(m.OrderMessage.created_at, m.OrderMessage.id)
            .limit(limit)
        )
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
        is_read=row.is_read, created_at=row.created_at,
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
