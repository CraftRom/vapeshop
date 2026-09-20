"""Канонічна бізнес-класифікація замовлення для статистики й клієнтських totals.

Локальний ``Order.status`` — це workflow магазину: NEW/ACCEPTED/PAID/SHIPPED/DONE.
Він відповідає на питання «на якому технічному етапі замовлення», але НЕ на
питання «чи це вже продаж». Для CRM-пов'язаних замовлень комерційний результат
визначає авторитетний статус SalesDrive:

* ``Продаж``  -> sale;
* ``Відмова`` -> refusal;
* будь-який інший відомий CRM-статус -> pending.

Для старих замовлень, які ніколи не були пов'язані з CRM, лишається вузький
fallback: DONE -> sale, CANCELLED -> refusal. Завдяки цьому стара історія не
зникає зі статистики, але ACCEPTED/PAID/SHIPPED більше не називаються продажем.
"""
from __future__ import annotations

from datetime import datetime, timezone

from shop.entities import OrderStatus

BUSINESS_PENDING = "pending"
BUSINESS_SALE = "sale"
BUSINESS_REFUSAL = "refusal"
BUSINESS_STATES = frozenset({BUSINESS_PENDING, BUSINESS_SALE, BUSINESS_REFUSAL})

CRM_SALE_STATUS_NAME = "Продаж"
CRM_REFUSAL_STATUS_NAME = "Відмова"


def normalize_crm_status_name(value) -> str:
    """Стабільне порівняння CRM-підписів без зайвих пробілів/регістру."""
    return " ".join(str(value or "").split()).casefold()


def state_from_crm_status_name(value) -> str | None:
    """Повертає бізнес-стан для *відомої* назви CRM.

    ``None`` означає, що назви взагалі немає і робити висновок не можна.
    Відома назва, яка не є «Продаж»/«Відмова», є ``pending``.
    """
    raw = " ".join(str(value or "").split())
    if not raw:
        return None
    normalized = raw.casefold()
    if normalized == CRM_SALE_STATUS_NAME.casefold():
        return BUSINESS_SALE
    if normalized == CRM_REFUSAL_STATUS_NAME.casefold():
        return BUSINESS_REFUSAL
    return BUSINESS_PENDING


def state_from_legacy_status(status) -> str:
    """Комерційний результат для замовлення, яке ніколи не мало CRM."""
    try:
        value = status.value
    except AttributeError:
        value = str(status or "").lower()
    if value == OrderStatus.DONE.value:
        return BUSINESS_SALE
    if value == OrderStatus.CANCELLED.value:
        return BUSINESS_REFUSAL
    return BUSINESS_PENDING


def has_crm_authority(order) -> bool:
    """Чи повинен комерційний результат визначатись CRM, а не local workflow."""
    if (getattr(order, "crm_id", None) or getattr(order, "crm_status_id", None)
            or getattr(order, "crm_state", None)):
        return True
    if getattr(order, "crm_status_name", None):
        return True
    snapshot = getattr(order, "crm_snapshot", None)
    return isinstance(snapshot, dict) and bool(snapshot.get("statusId") or snapshot.get("statusName"))


def effective_crm_status_name(order) -> str:
    direct = str(getattr(order, "crm_status_name", None) or "").strip()
    if direct:
        return direct
    snapshot = getattr(order, "crm_snapshot", None)
    if isinstance(snapshot, dict):
        return str(snapshot.get("statusName") or "").strip()
    return ""


def derive_business_state(order) -> str:
    """Безпечна реконструкція, якщо persisted business_state ще відсутній."""
    stored = str(getattr(order, "business_state", None) or "").strip().lower()
    if stored in BUSINESS_STATES:
        return stored
    if has_crm_authority(order):
        state = state_from_crm_status_name(effective_crm_status_name(order))
        # Нерозв'язаний CRM statusId не можна вважати продажем за local status.
        return state or BUSINESS_PENDING
    return state_from_legacy_status(getattr(order, "status", None))


def is_sale(order) -> bool:
    return derive_business_state(order) == BUSINESS_SALE


def is_refusal(order) -> bool:
    return derive_business_state(order) == BUSINESS_REFUSAL


def event_time(order) -> datetime | None:
    """Коли поточний комерційний результат набув чинності.

    Нові записи мають ``business_state_at``. Для legacy даних fallback не
    вигадує точний момент: використовує updated_at/created_at лише як
    найкращий доступний історичний орієнтир.
    """
    return (
        getattr(order, "business_state_at", None)
        or getattr(order, "updated_at", None)
        or getattr(order, "created_at", None)
    )


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
