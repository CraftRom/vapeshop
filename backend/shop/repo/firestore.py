"""Репозиторій поверх Firestore — для Vercel та іншого serverless.

Три речі, які принципово відрізняються від SQL:

1. **Гроші зберігаються в копійках (int).** У Firestore немає Decimal, а float
   для грошей — джерело помилок округлення. Конвертація на межі репозиторію.

2. **Немає JOIN і GROUP BY.** Тому лічильники (orders_count, total_spent,
   referrals_count, products_count, used_count) підтримуються при записі
   атомарними інкрементами, а не рахуються при читанні.

3. **Немає пошуку підрядка.** Пошук зроблено префіксним через діапазон
   [запит, запит + '\\uf8ff'] по денормалізованому полю в нижньому регістрі.
"""
from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from shop.entities import (
    PAID_STATUSES, Broadcast, BroadcastStatus, CartLine, Category, Order,
    OrderLine, OrderStatus, Product, Promo, PromoType, Stats, User,
)
from shop.repo.base import Repository
from shop.repo.docstore import DocStore, Inc

ALPHABET = string.ascii_uppercase + string.digits
PAID_VALUES = [s.value for s in PAID_STATUSES]

USERS, CATEGORIES, PRODUCTS = "users", "categories", "products"
CARTS, ORDERS, PROMOS = "carts", "orders", "promos"
PROMO_USES, BONUS_TX, BROADCASTS = "promo_uses", "bonus_tx", "broadcasts"
SETTINGS, SETTINGS_DOC = "settings", "shop"

# Найбільша кодова точка — межа префіксного діапазону в Firestore
PREFIX_END = "\uf8ff"


def to_cents(value) -> int:
    return int((Decimal(str(value or 0)) * 100).to_integral_value())


def from_cents(value) -> Decimal:
    return (Decimal(int(value or 0)) / 100).quantize(Decimal("0.01"))


def user_search_key(username, first_name, phone) -> str:
    return " ".join(filter(None, [username, first_name, phone])).lower()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _dt(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------- перетворення

def _user(d: dict | None) -> User | None:
    if not d:
        return None
    return User(
        id=d["id"], tg_id=d["tg_id"], referral_code=d["referral_code"],
        username=d.get("username"), first_name=d.get("first_name"),
        phone=d.get("phone"), full_name=d.get("full_name"),
        age_confirmed=d.get("age_confirmed", False),
        is_blocked=d.get("is_blocked", False), referrer_id=d.get("referrer_id"),
        bonus_balance=from_cents(d.get("bonus_balance_cents")),
        orders_count=d.get("orders_count", 0),
        total_spent=from_cents(d.get("total_spent_cents")),
        referrals_count=d.get("referrals_count", 0),
        created_at=_dt(d.get("created_at")), last_seen_at=_dt(d.get("last_seen_at")),
    )


def _product(d: dict | None) -> Product | None:
    if not d:
        return None
    return Product(
        id=d["id"], category_id=d["category_id"], name=d["name"],
        price=from_cents(d.get("price_cents")), description=d.get("description"),
        old_price=from_cents(d["old_price_cents"]) if d.get("old_price_cents") else None,
        stock=d.get("stock", 0), photo_file_id=d.get("photo_file_id"),
        photo_url=d.get("photo_url"), sort_order=d.get("sort_order", 0),
        is_active=d.get("is_active", True), category_name=d.get("category_name"),
        name_lower=d.get("name_lower", ""),
    )


def _order(d: dict | None) -> Order | None:
    if not d:
        return None
    return Order(
        id=d["id"], user_id=d["user_id"], status=OrderStatus(d.get("status", "new")),
        subtotal=from_cents(d.get("subtotal_cents")),
        discount=from_cents(d.get("discount_cents")),
        bonus_used=from_cents(d.get("bonus_used_cents")),
        total=from_cents(d.get("total_cents")),
        promo_code_id=d.get("promo_code_id"), payment_method=d.get("payment_method"),
        receipt_file_id=d.get("receipt_file_id"), contact_name=d.get("contact_name"),
        contact_phone=d.get("contact_phone"), delivery_city=d.get("delivery_city"),
        delivery_address=d.get("delivery_address"), comment=d.get("comment"),
        admin_note=d.get("admin_note"), referral_paid=d.get("referral_paid", False),
        created_at=_dt(d.get("created_at")), search_key=d.get("search_key", ""),
        items=[
            OrderLine(name=i["name"], price=from_cents(i["price_cents"]),
                      qty=i["qty"], product_id=i.get("product_id"))
            for i in d.get("items", [])
        ],
    )


def _promo(d: dict | None) -> Promo | None:
    if not d:
        return None
    return Promo(
        id=d["id"], code=d["code"], type=PromoType(d.get("type", "percent")),
        value=from_cents(d.get("value_cents")), min_order=from_cents(d.get("min_order_cents")),
        max_uses=d.get("max_uses"), per_user_limit=d.get("per_user_limit", 1),
        used_count=d.get("used_count", 0), expires_at=_dt(d.get("expires_at")),
        is_active=d.get("is_active", True), created_at=_dt(d.get("created_at")),
    )


def _broadcast(d: dict | None) -> Broadcast | None:
    if not d:
        return None
    return Broadcast(
        id=d["id"], title=d["title"], text=d["text"], photo_url=d.get("photo_url"),
        button_text=d.get("button_text"), button_url=d.get("button_url"),
        segment=d.get("segment") or {}, status=BroadcastStatus(d.get("status", "draft")),
        sent_count=d.get("sent_count", 0), failed_count=d.get("failed_count", 0),
        cursor_id=d.get("cursor_id", 0), created_at=_dt(d.get("created_at")),
        finished_at=_dt(d.get("finished_at")),
    )


class FirestoreRepository(Repository):
    def __init__(self, store: DocStore) -> None:
        self.db = store

    # ------------------------------------------------------------ users

    async def get_user_by_tg(self, tg_id: int) -> User | None:
        rows = await self.db.query(USERS, [("tg_id", "==", tg_id)], limit=1)
        return _user(rows[0]) if rows else None

    async def get_user(self, user_id: int) -> User | None:
        return _user(await self.db.get(USERS, user_id))

    async def get_user_by_referral_code(self, code: str) -> User | None:
        rows = await self.db.query(USERS, [("referral_code", "==", code)], limit=1)
        return _user(rows[0]) if rows else None

    async def _unique_code(self) -> str:
        while True:
            code = "".join(secrets.choice(ALPHABET) for _ in range(8))
            if not await self.db.query(USERS, [("referral_code", "==", code)], limit=1):
                return code

    async def create_user(self, tg_id, username, first_name, referrer_id) -> User:
        user_id = await self.db.next_id(USERS)
        now = _iso(_now())
        doc = {
            "id": user_id, "tg_id": tg_id, "username": username, "first_name": first_name,
            "phone": None, "full_name": None, "referral_code": await self._unique_code(),
            "referrer_id": referrer_id, "age_confirmed": False, "is_blocked": False,
            "bonus_balance_cents": 0, "orders_count": 0, "total_spent_cents": 0,
            "referrals_count": 0, "created_at": now, "last_seen_at": now,
            "search_key": user_search_key(username, first_name, None),
        }
        await self.db.set(USERS, user_id, doc)
        if referrer_id:
            await self.db.update(USERS, referrer_id, {"referrals_count": Inc(1)})
        return _user(doc)

    async def touch_user(self, user, username, first_name) -> User:
        await self.db.update(USERS, user.id, {
            "username": username or user.username,
            "first_name": first_name or user.first_name,
            "last_seen_at": _iso(_now()),
            "search_key": user_search_key(
                username or user.username, first_name or user.first_name, user.phone
            ),
        })
        user.username = username or user.username
        user.first_name = first_name or user.first_name
        return user

    async def set_user_referrer(self, user, referrer_id: int) -> None:
        await self.db.update(USERS, user.id, {"referrer_id": referrer_id})
        await self.db.update(USERS, referrer_id, {"referrals_count": Inc(1)})
        user.referrer_id = referrer_id

    async def confirm_age(self, user) -> None:
        await self.db.update(USERS, user.id, {"age_confirmed": True})
        user.age_confirmed = True

    async def set_blocked(self, user_id, blocked) -> User | None:
        if not await self.db.update(USERS, user_id, {"is_blocked": blocked}):
            return None
        return _user(await self.db.get(USERS, user_id))

    async def add_bonus(self, user_id, amount, reason, order_id=None) -> None:
        cents = to_cents(amount)
        tx_id = await self.db.next_id(BONUS_TX)
        await self.db.set(BONUS_TX, tx_id, {
            "id": tx_id, "user_id": user_id, "amount_cents": cents,
            "reason": reason, "order_id": order_id, "created_at": _iso(_now()),
        })
        await self.db.update(USERS, user_id, {"bonus_balance_cents": Inc(cents)})

    async def update_user_totals(self, user_id, orders_delta, spent_delta) -> None:
        await self.db.update(USERS, user_id, {
            "orders_count": Inc(orders_delta),
            "total_spent_cents": Inc(to_cents(spent_delta)),
        })

    async def list_users(self, search=None, blocked=None, limit=100, offset=0) -> list[User]:
        filters = []
        if blocked is not None:
            filters.append(("is_blocked", "==", blocked))
        rows = await self.db.query(
            USERS, filters, order_by=[("created_at", "desc")],
            limit=None if search else limit, offset=0 if search else offset,
        )
        if search:
            # Firestore не вміє шукати підрядок — фільтруємо по денормалізованому
            # полю на клієнті. Прийнятно: це адмінський список, не гарячий шлях.
            needle = search.lower()
            rows = [r for r in rows if needle in r.get("search_key", "")][offset:offset + limit]
        return [_user(r) for r in rows]

    # ---------------------------------------------------------- catalog

    async def list_categories(self, only_active=False) -> list[Category]:
        filters = [("is_active", "==", True)] if only_active else []
        rows = await self.db.query(
            CATEGORIES, filters, order_by=[("sort_order", "asc"), ("name", "asc")]
        )
        return [
            Category(
                id=r["id"], name=r["name"], description=r.get("description"),
                sort_order=r.get("sort_order", 0), is_active=r.get("is_active", True),
                products_count=r.get("products_count", 0),
            )
            for r in rows
        ]

    async def get_category(self, category_id) -> Category | None:
        d = await self.db.get(CATEGORIES, category_id)
        if not d:
            return None
        return Category(
            id=d["id"], name=d["name"], description=d.get("description"),
            sort_order=d.get("sort_order", 0), is_active=d.get("is_active", True),
            products_count=d.get("products_count", 0),
        )

    async def create_category(self, data: dict) -> Category:
        cat_id = await self.db.next_id(CATEGORIES)
        doc = {
            "id": cat_id, "name": data["name"], "description": data.get("description"),
            "sort_order": data.get("sort_order", 0),
            "is_active": data.get("is_active", True), "products_count": 0,
        }
        await self.db.set(CATEGORIES, cat_id, doc)
        return await self.get_category(cat_id)

    async def update_category(self, category_id, data: dict) -> Category | None:
        if not await self.db.update(CATEGORIES, category_id, dict(data)):
            return None
        return await self.get_category(category_id)

    async def delete_category(self, category_id) -> int:
        rows = await self.db.query(
            PRODUCTS, [("category_id", "==", category_id), ("is_active", "==", True)]
        )
        for row in rows:
            await self.db.update(PRODUCTS, row["id"], {"is_active": False})
        await self.db.update(CATEGORIES, category_id, {"is_active": False})
        return len(rows)

    async def list_products(
        self, category_id=None, search=None, only_active=False, limit=500, offset=0
    ) -> list[Product]:
        filters = []
        if category_id:
            filters.append(("category_id", "==", category_id))
        if only_active:
            filters.append(("is_active", "==", True))

        if search:
            # Префіксний пошук діапазоном — єдиний доступний у Firestore.
            # Діапазонний фільтр вимагає сортування за тим самим полем.
            needle = search.lower()
            filters += [("name_lower", ">=", needle), ("name_lower", "<=", needle + PREFIX_END)]
            order_by = [("name_lower", "asc")]
        else:
            order_by = [("sort_order", "asc"), ("name", "asc")]

        rows = await self.db.query(PRODUCTS, filters, order_by=order_by,
                                   limit=limit, offset=offset)
        return [_product(r) for r in rows]

    async def count_products(self, category_id, only_active=True) -> int:
        filters = [("category_id", "==", category_id)]
        if only_active:
            filters.append(("is_active", "==", True))
        return await self.db.count(PRODUCTS, filters)

    async def get_product(self, product_id) -> Product | None:
        return _product(await self.db.get(PRODUCTS, product_id))

    async def create_product(self, data: dict) -> Product:
        product_id = await self.db.next_id(PRODUCTS)
        category = await self.get_category(data["category_id"])
        doc = {
            "id": product_id, "category_id": data["category_id"], "name": data["name"],
            "name_lower": data["name"].lower(), "description": data.get("description"),
            "price_cents": to_cents(data["price"]),
            "old_price_cents": to_cents(data["old_price"]) if data.get("old_price") else None,
            "stock": data.get("stock", 0), "photo_file_id": data.get("photo_file_id"),
            "photo_url": data.get("photo_url"), "sort_order": data.get("sort_order", 0),
            "is_active": data.get("is_active", True),
            "category_name": category.name if category else None,
        }
        await self.db.set(PRODUCTS, product_id, doc)
        await self.db.update(CATEGORIES, data["category_id"], {"products_count": Inc(1)})
        return _product(doc)

    async def update_product(self, product_id, data: dict) -> Product | None:
        current = await self.db.get(PRODUCTS, product_id)
        if not current:
            return None
        payload: dict = {}
        for key, value in data.items():
            if key == "price":
                payload["price_cents"] = to_cents(value)
            elif key == "old_price":
                payload["old_price_cents"] = to_cents(value) if value else None
            elif key == "name":
                payload["name"] = value
                payload["name_lower"] = value.lower()
            else:
                payload[key] = value

        # Товар переїхав у іншу категорію — лічильники обох треба поправити
        new_category = data.get("category_id")
        if new_category and new_category != current["category_id"]:
            await self.db.update(CATEGORIES, current["category_id"], {"products_count": Inc(-1)})
            await self.db.update(CATEGORIES, new_category, {"products_count": Inc(1)})
            category = await self.get_category(new_category)
            payload["category_name"] = category.name if category else None

        await self.db.update(PRODUCTS, product_id, payload)
        return _product(await self.db.get(PRODUCTS, product_id))

    async def adjust_stock(self, product_id, delta: int) -> Product | None:
        current = await self.db.get(PRODUCTS, product_id)
        if not current:
            return None
        # Inc атомарний, але не вміє обмежувати знизу — тому не даємо
        # запиту опуститись нижче наявного залишку.
        safe_delta = max(delta, -current.get("stock", 0))
        await self.db.update(PRODUCTS, product_id, {"stock": Inc(safe_delta)})
        return _product(await self.db.get(PRODUCTS, product_id))

    async def set_stock(self, product_id, stock: int) -> Product | None:
        if not await self.db.update(PRODUCTS, product_id, {"stock": max(0, stock)}):
            return None
        return _product(await self.db.get(PRODUCTS, product_id))

    async def count_low_stock(self, threshold=5) -> int:
        return await self.db.count(
            PRODUCTS, [("is_active", "==", True), ("stock", "<", threshold)]
        )

    # ------------------------------------------------------------- cart

    def _cart_id(self, user_id, product_id) -> str:
        return f"{user_id}_{product_id}"

    async def get_cart(self, user_id) -> list[CartLine]:
        rows = await self.db.query(
            CARTS, [("user_id", "==", user_id)], order_by=[("added_at", "asc")]
        )
        lines = []
        for row in rows:
            product = await self.get_product(row["product_id"])
            lines.append(CartLine(product_id=row["product_id"], qty=row["qty"], product=product))
        return lines

    async def set_cart_qty(self, user_id, product_id, qty: int) -> None:
        doc_id = self._cart_id(user_id, product_id)
        if qty <= 0:
            await self.db.delete(CARTS, doc_id)
            return
        existing = await self.db.get(CARTS, doc_id)
        await self.db.set(CARTS, doc_id, {
            "user_id": user_id, "product_id": product_id, "qty": qty,
            "added_at": existing["added_at"] if existing else _iso(_now()),
        })

    async def clear_cart(self, user_id) -> None:
        for row in await self.db.query(CARTS, [("user_id", "==", user_id)]):
            await self.db.delete(CARTS, self._cart_id(user_id, row["product_id"]))

    # ----------------------------------------------------------- orders

    async def create_order(self, order: Order, lines: list[OrderLine]) -> Order:
        order_id = await self.db.next_id(ORDERS)
        doc = {
            "id": order_id, "user_id": order.user_id, "status": OrderStatus.NEW.value,
            "subtotal_cents": to_cents(order.subtotal),
            "discount_cents": to_cents(order.discount),
            "bonus_used_cents": to_cents(order.bonus_used),
            "total_cents": to_cents(order.total),
            "promo_code_id": order.promo_code_id, "payment_method": order.payment_method,
            "receipt_file_id": None, "contact_name": order.contact_name,
            "contact_phone": order.contact_phone, "delivery_city": order.delivery_city,
            "delivery_address": order.delivery_address, "comment": order.comment,
            "admin_note": None, "referral_paid": False,
            "search_key": f"{order.contact_name or ''} {order.contact_phone or ''}".lower(),
            "created_at": _iso(_now()),
            # Позиції — вкладений масив: замовлення завжди читається цілком,
            # окрема колекція означала б зайвий запит на кожен показ.
            "items": [
                {"product_id": ln.product_id, "name": ln.name,
                 "price_cents": to_cents(ln.price), "qty": ln.qty}
                for ln in lines
            ],
        }
        await self.db.set(ORDERS, order_id, doc)
        return _order(doc)

    async def get_order(self, order_id) -> Order | None:
        entity = _order(await self.db.get(ORDERS, order_id))
        if entity:
            entity.user = await self.get_user(entity.user_id)
        return entity

    async def list_orders(self, status=None, search=None, user_id=None, limit=100, offset=0):
        filters = []
        if status:
            filters.append(("status", "==", status.value))
        if user_id:
            filters.append(("user_id", "==", user_id))
        rows = await self.db.query(
            ORDERS, filters, order_by=[("created_at", "desc")],
            limit=None if search else limit, offset=0 if search else offset,
        )
        if search:
            needle = search.lower()
            rows = [r for r in rows if needle in r.get("search_key", "")][offset:offset + limit]

        orders = []
        cache: dict[int, User | None] = {}
        for row in rows:
            entity = _order(row)
            if entity.user_id not in cache:
                cache[entity.user_id] = await self.get_user(entity.user_id)
            entity.user = cache[entity.user_id]
            orders.append(entity)
        return orders

    async def update_order(self, order_id, data: dict) -> Order | None:
        payload = {}
        for key, value in data.items():
            if key == "status":
                payload["status"] = value.value if hasattr(value, "value") else value
            elif key.endswith("_cents") or not isinstance(value, Decimal):
                payload[key] = value
            else:
                payload[f"{key}_cents"] = to_cents(value)
        if not await self.db.update(ORDERS, order_id, payload):
            return None
        return await self.get_order(order_id)

    async def count_orders(self, status=None) -> int:
        filters = [("status", "==", status.value)] if status else []
        return await self.db.count(ORDERS, filters)

    async def status_breakdown(self) -> dict[str, int]:
        result = {}
        for status in OrderStatus:
            count = await self.db.count(ORDERS, [("status", "==", status.value)])
            if count:
                result[status.value] = count
        return result

    # ----------------------------------------------------------- promos

    async def get_promo_by_code(self, code: str) -> Promo | None:
        rows = await self.db.query(
            PROMOS, [("code", "==", code.strip().upper())], limit=1
        )
        return _promo(rows[0]) if rows else None

    async def get_promo(self, promo_id) -> Promo | None:
        return _promo(await self.db.get(PROMOS, promo_id))

    async def list_promos(self) -> list[Promo]:
        rows = await self.db.query(PROMOS, order_by=[("created_at", "desc")])
        return [_promo(r) for r in rows]

    def _promo_doc(self, promo_id: int, data: dict) -> dict:
        ptype = data.get("type", PromoType.PERCENT)
        expires = data.get("expires_at")
        return {
            "id": promo_id, "code": data["code"].strip().upper(),
            "type": ptype.value if hasattr(ptype, "value") else ptype,
            "value_cents": to_cents(data["value"]),
            "min_order_cents": to_cents(data.get("min_order", 0)),
            "max_uses": data.get("max_uses"),
            "per_user_limit": data.get("per_user_limit", 1),
            "expires_at": _iso(expires) if isinstance(expires, datetime) else expires,
            "is_active": data.get("is_active", True),
        }

    async def create_promo(self, data: dict) -> Promo:
        promo_id = await self.db.next_id(PROMOS)
        doc = self._promo_doc(promo_id, data) | {
            "used_count": 0, "created_at": _iso(_now()),
        }
        await self.db.set(PROMOS, promo_id, doc)
        return _promo(doc)

    async def update_promo(self, promo_id, data: dict) -> Promo | None:
        current = await self.db.get(PROMOS, promo_id)
        if not current:
            return None
        if "code" in data and "value" in data:
            payload = self._promo_doc(promo_id, data)
        else:
            payload = {k: v for k, v in data.items() if k in ("is_active", "used_count")}
        await self.db.update(PROMOS, promo_id, payload)
        return _promo(await self.db.get(PROMOS, promo_id))

    async def promo_uses_by_user(self, promo_id, user_id) -> int:
        return await self.db.count(
            PROMO_USES, [("promo_id", "==", promo_id), ("user_id", "==", user_id)]
        )

    async def register_promo_use(self, promo_id, user_id, order_id) -> None:
        use_id = await self.db.next_id(PROMO_USES)
        await self.db.set(PROMO_USES, use_id, {
            "id": use_id, "promo_id": promo_id, "user_id": user_id,
            "order_id": order_id, "created_at": _iso(_now()),
        })
        await self.db.update(PROMOS, promo_id, {"used_count": Inc(1)})

    # ------------------------------------------------------- broadcasts

    async def list_broadcasts(self) -> list[Broadcast]:
        rows = await self.db.query(BROADCASTS, order_by=[("created_at", "desc")])
        return [_broadcast(r) for r in rows]

    async def get_broadcast(self, broadcast_id) -> Broadcast | None:
        return _broadcast(await self.db.get(BROADCASTS, broadcast_id))

    async def create_broadcast(self, data: dict) -> Broadcast:
        broadcast_id = await self.db.next_id(BROADCASTS)
        doc = {
            "id": broadcast_id, "title": data["title"], "text": data["text"],
            "photo_url": data.get("photo_url"), "button_text": data.get("button_text"),
            "button_url": data.get("button_url"), "segment": data.get("segment") or {},
            "status": BroadcastStatus.DRAFT.value, "sent_count": 0, "failed_count": 0,
            "cursor_id": 0, "created_at": _iso(_now()), "finished_at": None,
        }
        await self.db.set(BROADCASTS, broadcast_id, doc)
        return _broadcast(doc)

    async def update_broadcast(self, broadcast_id, data: dict) -> Broadcast | None:
        payload = {}
        for key, value in data.items():
            if key in ("status",):
                payload[key] = value.value if hasattr(value, "value") else value
            elif key in ("finished_at",):
                payload[key] = _iso(value) if isinstance(value, datetime) else value
            else:
                payload[key] = value
        if not await self.db.update(BROADCASTS, broadcast_id, payload):
            return None
        return _broadcast(await self.db.get(BROADCASTS, broadcast_id))

    async def delete_broadcast(self, broadcast_id) -> bool:
        return await self.db.delete(BROADCASTS, broadcast_id)

    async def next_pending_broadcast(self) -> Broadcast | None:
        rows = await self.db.query(
            BROADCASTS, [("status", "==", BroadcastStatus.SENDING.value)],
            order_by=[("created_at", "asc")], limit=1,
        )
        return _broadcast(rows[0]) if rows else None

    # --------------------------------------------------------- segments

    def _segment_filters(self, segment: dict) -> list:
        stype = (segment or {}).get("type", "all")
        base = [("is_blocked", "==", False), ("age_confirmed", "==", True)]
        if stype == "with_orders":
            return base + [("orders_count", ">", 0)]
        if stype == "no_orders":
            return base + [("orders_count", "==", 0)]
        if stype == "inactive":
            cutoff = _now() - timedelta(days=int(segment.get("days", 30)))
            return base + [("last_seen_at", "<", _iso(cutoff))]
        if stype == "top_spenders":
            return base + [("total_spent_cents", ">=", to_cents(segment.get("min_total", 1000)))]
        if stype == "with_referrals":
            return base + [("referrals_count", ">", 0)]
        return base

    async def count_segment(self, segment: dict) -> int:
        return await self.db.count(USERS, self._segment_filters(segment))

    async def segment_recipients(self, segment, cursor_id, limit):
        # Firestore не дозволяє діапазонні фільтри по двох різних полях одразу.
        # Тому курсор застосовуємо після вибірки, а не в запиті.
        filters = self._segment_filters(segment)
        range_fields = {f for f, op, _ in filters if op not in ("==", "in")}

        if range_fields:
            rows = await self.db.query(USERS, filters, order_by=[(next(iter(range_fields)), "asc")])
            rows = sorted(rows, key=lambda r: r["id"])
            rows = [r for r in rows if r["id"] > cursor_id][:limit]
        else:
            rows = await self.db.query(
                USERS, filters + [("id", ">", cursor_id)],
                order_by=[("id", "asc")], limit=limit,
            )
        return [(r["id"], r["tg_id"]) for r in rows]

    # ------------------------------------------------------------ stats

    async def stats_summary(self, days: int) -> Stats:
        since = _iso(_now() - timedelta(days=days))
        paid = await self.db.query(ORDERS, [("status", "in", PAID_VALUES)])

        revenue_total = sum(r.get("total_cents", 0) for r in paid)
        revenue_period = sum(
            r.get("total_cents", 0) for r in paid if (r.get("created_at") or "") >= since
        )
        users = await self.db.query(USERS)

        return Stats(
            revenue_total=from_cents(revenue_total),
            revenue_period=from_cents(revenue_period),
            orders_total=await self.db.count(ORDERS),
            orders_new=await self.db.count(ORDERS, [("status", "==", OrderStatus.NEW.value)]),
            customers_total=len(users),
            customers_period=sum(1 for u in users if (u.get("created_at") or "") >= since),
            avg_check=from_cents(revenue_total // len(paid)) if paid else Decimal(0),
            low_stock=await self.count_low_stock(),
        )

    async def stats_series(self, days: int) -> list[dict]:
        since = _iso(_now() - timedelta(days=days))
        rows = await self.db.query(ORDERS, [("status", "in", PAID_VALUES)])
        buckets: dict[str, dict] = {}
        for row in rows:
            created = row.get("created_at") or ""
            if created < since:
                continue
            key = created[:10]
            bucket = buckets.setdefault(key, {"date": key, "revenue": Decimal(0), "orders": 0})
            bucket["revenue"] += from_cents(row.get("total_cents"))
            bucket["orders"] += 1
        return [buckets[k] for k in sorted(buckets)]

    async def stats_top_products(self, days: int, limit: int) -> list[dict]:
        since = _iso(_now() - timedelta(days=days))
        rows = await self.db.query(ORDERS, [("status", "in", PAID_VALUES)])
        totals: dict[str, dict] = {}
        for row in rows:
            if (row.get("created_at") or "") < since:
                continue
            for item in row.get("items", []):
                entry = totals.setdefault(
                    item["name"], {"name": item["name"], "qty": 0, "revenue": Decimal(0)}
                )
                entry["qty"] += item["qty"]
                entry["revenue"] += from_cents(item["price_cents"] * item["qty"])
        return sorted(totals.values(), key=lambda e: e["revenue"], reverse=True)[:limit]

    # --------------------------------------------------- налаштування

    async def get_settings_map(self) -> dict[str, str]:
        doc = await self.db.get(SETTINGS, SETTINGS_DOC)
        return {k: v for k, v in (doc or {}).items() if k != "id"}

    async def save_settings_map(self, values: dict[str, str]) -> None:
        payload = {key: str(value) for key, value in values.items()}
        if not await self.db.update(SETTINGS, SETTINGS_DOC, dict(payload)):
            await self.db.set(SETTINGS, SETTINGS_DOC, {"id": SETTINGS_DOC, **payload})

    async def close(self) -> None:
        await self.db.close()
