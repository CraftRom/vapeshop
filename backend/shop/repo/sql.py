"""Репозиторій поверх SQLAlchemy — для власного сервера."""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shop import models as m
from shop.entities import (
    PAID_STATUSES, Broadcast, BroadcastStatus, CartLine, Category, Order,
    OrderLine, OrderStatus, Product, Promo, Stats, User,
)
from shop.repo.base import Repository

ALPHABET = string.ascii_uppercase + string.digits
PAID_SQL = [OrderStatus(s.value) for s in PAID_STATUSES]


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
        is_blocked=row.is_blocked, referrer_id=row.referrer_id,
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
        contact_phone=row.contact_phone, delivery_city=row.delivery_city,
        delivery_address=row.delivery_address, comment=row.comment,
        admin_note=row.admin_note, referral_paid=row.referral_paid,
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
        cursor_id=row.cursor_id, created_at=row.created_at, finished_at=row.finished_at,
    )


class SqlRepository(Repository):
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

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
        await self.s.commit()
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
        await self.s.commit()
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
        await self.s.commit()
        user.referrer_id = referrer_id

    async def confirm_age(self, user) -> None:
        await self.s.execute(
            update(m.User).where(m.User.id == user.id).values(age_confirmed=True)
        )
        await self.s.commit()
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
        await self.s.commit()

    async def update_user_totals(self, user_id, orders_delta, spent_delta) -> None:
        await self.s.execute(
            update(m.User).where(m.User.id == user_id).values(
                orders_count=func.max(0, m.User.orders_count + orders_delta),
                total_spent=func.max(0, m.User.total_spent + spent_delta),
            )
        )
        await self.s.commit()

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

    async def delete_category(self, category_id) -> bool:
        count = await self.s.scalar(
            select(func.count(m.Product.id)).where(m.Product.category_id == category_id)
        )
        if count:
            return False
        row = await self.s.get(m.Category, category_id)
        if row:
            await self.s.delete(row)
            await self.s.commit()
        return True

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
            .values(stock=func.max(0, m.Product.stock + delta))
        )
        await self.s.commit()
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
        await self.s.commit()

    # ----------------------------------------------------------- orders

    async def create_order(self, order: Order, lines: list[OrderLine]) -> Order:
        row = m.Order(
            user_id=order.user_id, subtotal=order.subtotal, discount=order.discount,
            bonus_used=order.bonus_used, total=order.total,
            promo_code_id=order.promo_code_id, payment_method=order.payment_method,
            contact_name=order.contact_name, contact_phone=order.contact_phone,
            delivery_city=order.delivery_city, delivery_address=order.delivery_address,
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

    async def list_orders(self, status=None, search=None, user_id=None, limit=100, offset=0):
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
        await self.s.commit()

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
        since = datetime.now(timezone.utc) - timedelta(days=days)
        paid = m.Order.status.in_(PAID_SQL)

        revenue_total = await self.s.scalar(
            select(func.coalesce(func.sum(m.Order.total), 0)).where(paid))
        revenue_period = await self.s.scalar(
            select(func.coalesce(func.sum(m.Order.total), 0))
            .where(paid, m.Order.created_at >= since))
        paid_count = await self.s.scalar(select(func.count(m.Order.id)).where(paid)) or 0

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
            low_stock=await self.count_low_stock(),
        )

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
        await self.s.commit()
