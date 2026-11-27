"""Репозиторій поверх SQLAlchemy — для власного сервера."""
from __future__ import annotations

from shop.services.attribution import order_attribution

import gzip
import json
import logging
import secrets
import string
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import and_, case, delete, exists, func, not_, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, lazyload, selectinload

from shop import models as m
from shop.entities import (
    Operator, OperatorRole, OrderMessage, SupportMessage, SupportThread, Wishlist,
    Broadcast, BroadcastStatus, CartLine, Category, Subcategory, Order,
    OrderLine, OrderStatus, Product, Promo, Stats, User,
)
from shop.repo.base import PromoCodeConflict, Repository
from shop.services import order_business as business
from shop.services.chat_access import aware, is_closed, record_completion
from shop.services.promo_rules import eligible_subtotal, promo_discount

ALPHABET = string.ascii_uppercase + string.digits
# Local status описує workflow, а не факт продажу. Єдиним джерелом продажу
# для статистики є persisted business_state (CRM «Продаж» -> sale).
SHIPPED_SQL = [OrderStatus.SHIPPED, OrderStatus.DONE]
SHIPPED_VALUES = frozenset(status.value for status in SHIPPED_SQL)
log = logging.getLogger("shop.repo.sql")

ARCHIVE_CODEC = "gzip-json-v1"


def _archive_dt(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _archive_parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _archive_json(items: list[dict]) -> bytes:
    return json.dumps(items, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _pack_archive(items: list[dict]) -> bytes:
    return gzip.compress(_archive_json(items), compresslevel=6)


def _unpack_archive(row) -> list[dict]:
    if row is None or not getattr(row, "payload", None):
        return []
    try:
        if getattr(row, "codec", ARCHIVE_CODEC) != ARCHIVE_CODEC:
            return []
        value = json.loads(gzip.decompress(bytes(row.payload)).decode("utf-8"))
        return value if isinstance(value, list) else []
    except Exception:
        log.exception("Не вдалося прочитати message archive %s:%s", getattr(row, "kind", "?"), getattr(row, "entity_id", "?"))
        return []


def _order_message_to_archive(row) -> dict:
    return {
        "id": int(row.id), "order_id": int(row.order_id), "user_id": int(row.user_id),
        "direction": row.direction, "author": row.author or "", "text": row.text or "",
        "tg_message_id": row.tg_message_id,
        # Cold history навмисно не зберігає Telegram file_id: це довгоживучий
        # ключ доступу до чужого вкладення. Назва/тип лишаються для контексту.
        "file_id": None, "file_kind": row.file_kind, "file_name": row.file_name,
        "is_read": bool(row.is_read), "delivered": getattr(row, "delivered", None),
        "delivery_error": getattr(row, "delivery_error", None),
        "created_at": _archive_dt(row.created_at),
    }


def _support_message_to_archive(row) -> dict:
    return {
        "id": int(row.id), "thread_id": int(row.thread_id), "user_id": int(row.user_id),
        "direction": row.direction, "author": row.author or "", "text": row.text or "",
        "tg_message_id": row.tg_message_id, "file_id": None,
        "file_kind": row.file_kind, "file_name": row.file_name,
        "is_read": bool(row.is_read), "is_automatic": bool(getattr(row, "is_automatic", False)),
        "created_at": _archive_dt(row.created_at),
    }


def _archived_order_message(item: dict) -> OrderMessage:
    return OrderMessage(
        id=int(item.get("id") or 0), order_id=int(item.get("order_id") or 0),
        user_id=int(item.get("user_id") or 0), direction=str(item.get("direction") or ""),
        author=str(item.get("author") or ""), text=str(item.get("text") or ""),
        tg_message_id=item.get("tg_message_id"), file_id=None,
        file_kind=item.get("file_kind"), file_name=item.get("file_name"),
        is_read=bool(item.get("is_read")), delivered=item.get("delivered"),
        delivery_error=item.get("delivery_error"), created_at=_archive_parse_dt(item.get("created_at")),
    )


def _archived_support_message(item: dict) -> SupportMessage:
    return SupportMessage(
        id=int(item.get("id") or 0), thread_id=int(item.get("thread_id") or 0),
        user_id=int(item.get("user_id") or 0), direction=str(item.get("direction") or ""),
        author=str(item.get("author") or ""), text=str(item.get("text") or ""),
        tg_message_id=item.get("tg_message_id"), file_id=None,
        file_kind=item.get("file_kind"), file_name=item.get("file_name"),
        is_read=bool(item.get("is_read")), is_automatic=bool(item.get("is_automatic")),
        created_at=_archive_parse_dt(item.get("created_at")),
    )


def _emit_order_changed(order, fields=(), *, created: bool = False) -> None:
    """Best-effort realtime signal AFTER the DB transaction is committed.

    Redis/pubsub is deliberately not part of the transaction: a temporary
    Redis outage must never roll back a valid order. Open pages always have
    quota-safe polling as a fallback.
    """
    if order is None:
        return
    try:
        from shop.services.realtime import emit_order_changed
        emit_order_changed(
            int(order.id), user_id=int(order.user_id),
            fields=tuple(str(x) for x in fields), created=created,
        )
    except Exception:
        # Realtime is an acceleration path, never a source of truth.
        return


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


def stats_finance_values(business_state, local_status, payment_method, total, snapshot=None) -> dict:
    """Єдине фінансове правило статистики продажів.

    Продаж існує тільки коли ``business_state == sale``. Local ACCEPTED,
    PAID або SHIPPED більше не можуть самі створити оборот. Для картки після
    продажу повну суму вважаємо отриманою; для COD беремо тільки фактичний
    ``payedAmount`` SalesDrive, а решту показуємо як очікувану.
    """
    try:
        local_value = local_status.value
    except AttributeError:
        local_value = str(local_status or "")
    sold = str(business_state or "").strip().lower() == business.BUSINESS_SALE
    shipped = local_value in SHIPPED_VALUES
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

    if not sold:
        return {
            "total": Decimal(0), "sold": False, "shipped": shipped,
            "actual_received": Decimal(0), "calculated_received": Decimal(0),
            "received": Decimal(0), "expected": Decimal(0),
        }

    method = str(payment_method or "").lower()
    received = amount if method == "card" and amount > 0 else actual
    received = max(Decimal(0), min(amount, received))
    calculated = max(Decimal(0), received - actual)
    expected = max(Decimal(0), amount - received)

    return {
        "total": amount, "sold": True, "shipped": shipped,
        "actual_received": actual, "calculated_received": calculated,
        "received": received, "expected": expected,
    }


def _row_finance(row) -> dict:
    snap = _snapshot(row)
    return stats_finance_values(
        getattr(row, "business_state", business.BUSINESS_PENDING),
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


def _parents_active():
    """SQL: всі батьківські групи товару активні (correlated to m.Product)."""
    category, sub, sub_category = aliased(m.Category), aliased(m.Subcategory), aliased(m.Category)
    category_ok = or_(m.Product.category_id.is_(None), exists().where(
        category.id == m.Product.category_id, category.is_active.is_(True)))
    sub_ok = or_(m.Product.subcategory_id.is_(None), exists().where(
        sub.id == m.Product.subcategory_id, sub.is_active.is_(True),
        or_(sub.category_id.is_(None), exists().where(
            sub_category.id == sub.category_id, sub_category.is_active.is_(True)))))
    return and_(category_ok, sub_ok)


def _published():
    """Єдине правило публікації для вітрини, Mini App, бота, кошика й quote."""
    return and_(m.Product.is_active.is_(True), _parents_active())


def _product(row, category_name: str | None = None, subcategory_name: str | None = None,
             parent_active: bool = True) -> Product | None:
    if row is None:
        return None
    return Product(parent_active=bool(parent_active),
        id=row.id, category_id=row.category_id, name=row.name, sku=row.sku,
        subcategory_id=row.subcategory_id, subcategory_name=subcategory_name,
        external_sku=row.external_sku, is_new=row.is_new, is_sale=row.is_sale,
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
        attribution=order_attribution(row.attribution, row.crm_snapshot), checkout_key=row.checkout_key,
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
        business_state=row.business_state or "pending", business_state_at=row.business_state_at,
        operator_id=row.operator_id, operator_name=row.operator_name or "",
        completed_at=aware(row.completed_at) if row.completed_at else None, referral_paid=row.referral_paid,
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
        category_ids=list(row.category_ids or []),
    )


def _broadcast(row) -> Broadcast | None:
    if row is None:
        return None
    return Broadcast(
        id=row.id, title=row.title, text=row.text, photo_url=row.photo_url,
        text_format=row.text_format, client_key=row.client_key,
        button_text=row.button_text, button_url=row.button_url,
        segment=row.segment or {}, status=BroadcastStatus(row.status.value),
        sent_count=row.sent_count, failed_count=row.failed_count,
        cursor_id=row.cursor_id, scheduled_at=row.scheduled_at,
        unknown_count=row.unknown_count, lease_owner=row.lease_owner,
        lease_until=row.lease_until, heartbeat_at=row.heartbeat_at, last_error=row.last_error,
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


def _operator(row) -> Operator | None:
    if row is None:
        return None
    return Operator(
        id=row.id, login=row.login, name=row.name or "",
        role=OperatorRole(row.role), is_active=row.is_active,
        created_at=row.created_at, last_login_at=row.last_login_at,
        password_hash=row.password_hash, auth_version=row.auth_version,
    )


def _order_message(row) -> OrderMessage:
    return OrderMessage(
        id=row.id, order_id=row.order_id, user_id=row.user_id,
        direction=row.direction, author=row.author or "", text=row.text,
        tg_message_id=row.tg_message_id, is_read=row.is_read, created_at=row.created_at,
        file_id=row.file_id, file_kind=row.file_kind, file_name=row.file_name,
        delivered=getattr(row, "delivered", None),
        delivery_error=getattr(row, "delivery_error", None),
    )


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


__all__ = [
    'ALPHABET',
    'ARCHIVE_CODEC',
    'AsyncSession',
    'Broadcast',
    'BroadcastStatus',
    'CartLine',
    'Category',
    'Decimal',
    'IntegrityError',
    'Operator',
    'OperatorRole',
    'Order',
    'OrderLine',
    'OrderMessage',
    'OrderStatus',
    'Product',
    'Promo',
    'PromoCodeConflict',
    'Repository',
    'SHIPPED_SQL',
    'SHIPPED_VALUES',
    'Stats',
    'Subcategory',
    'SupportMessage',
    'SupportThread',
    'User',
    'Wishlist',
    '_archive_dt',
    '_archive_json',
    '_archive_parse_dt',
    '_archived_order_message',
    '_archived_support_message',
    '_aware',
    '_broadcast',
    '_category',
    '_change',
    '_dec',
    '_emit_order_changed',
    '_in_window',
    '_maybe_dec',
    '_not_below_zero',
    '_operator',
    '_order',
    '_order_message',
    '_order_message_to_archive',
    '_pack_archive',
    '_parents_active',
    '_product',
    '_promo',
    '_published',
    '_row_finance',
    '_snapshot',
    '_stats_payment_method',
    '_support_message',
    '_support_message_to_archive',
    '_support_thread',
    '_unpack_archive',
    '_user',
    '_wishlist',
    'aliased',
    'and_',
    'aware',
    'business',
    'case',
    'datetime',
    'delete',
    'eligible_subtotal',
    'exists',
    'func',
    'gzip',
    'is_closed',
    'json',
    'lazyload',
    'log',
    'logging',
    'm',
    'not_',
    'or_',
    'order_attribution',
    'promo_discount',
    'record_completion',
    'secrets',
    'select',
    'selectinload',
    'stats_finance_values',
    'string',
    'timedelta',
    'timezone',
    'update',
    'user_search_key',
]
