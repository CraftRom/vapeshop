"""Канонічна бізнес-класифікація замовлення для статистики й клієнтських totals.

Локальний ``Order.status`` — це workflow магазину: NEW/ACCEPTED/PAID/SHIPPED/DONE.
Він відповідає на питання «на якому технічному етапі замовлення», але НЕ на
питання «чи це вже продаж». Для CRM-пов'язаних замовлень комерційний результат
визначає авторитетний статус SalesDrive:

* ``Продаж`` -> sale;
* ``Відмова`` / ``Повернення`` / ``Видалений`` -> refusal;
* будь-який інший відомий CRM-статус -> pending.

Для старих замовлень, які ніколи не були пов'язані з CRM, лишається вузький
fallback: DONE -> sale, CANCELLED -> refusal. Завдяки цьому стара історія не
зникає зі статистики, але ACCEPTED/PAID/SHIPPED більше не називаються продажем.
"""
from __future__ import annotations

from datetime import datetime, timezone

from shop.entities import OrderStatus, STATUS_LABELS

BUSINESS_PENDING = "pending"
BUSINESS_SALE = "sale"
BUSINESS_REFUSAL = "refusal"
BUSINESS_STATES = frozenset({BUSINESS_PENDING, BUSINESS_SALE, BUSINESS_REFUSAL})

CRM_SALE_STATUS_NAME = "Продаж"

# Фінальні негативні результати SalesDrive. Це НЕ послідовні кроки після
# «Продаж», а взаємовиключні результати заявки. Тому всі вони мають один
# business_state=refusal і ніколи не повинні потрапляти в продажі/оборот.
CRM_REFUSAL_STATUS_NAMES = frozenset({
    "відмова",
    "повернення",
    "повернено",
    "видалений",
    "видалено",
    # Безпечні compatibility-аліаси для кабінетів з англійськими назвами.
    "refusal",
    "return",
    "returned",
    "deleted",
})


def normalize_crm_status_name(value) -> str:
    """Стабільне порівняння CRM-підписів без зайвих пробілів/регістру."""
    return " ".join(str(value or "").split()).casefold()


def state_from_crm_status_name(value) -> str | None:
    """Повертає бізнес-стан для *відомої* назви CRM.

    ``None`` означає, що назви взагалі немає і робити висновок не можна.
    «Продаж» є єдиним sale. «Відмова», «Повернення» та «Видалений» є
    негативним завершенням ``refusal``. Інші відомі CRM-статуси — ``pending``.
    """
    raw = " ".join(str(value or "").split())
    if not raw:
        return None
    normalized = raw.casefold()
    if normalized == CRM_SALE_STATUS_NAME.casefold():
        return BUSINESS_SALE
    if normalized in CRM_REFUSAL_STATUS_NAMES:
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


def display_status_label(order) -> str:
    """Human-readable status shared by customer-facing surfaces.

    For SalesDrive-linked orders CRM is the display authority. Local status
    remains the internal workflow and must not leak as a contradictory label
    when CRM already reports another state.
    """
    if has_crm_authority(order):
        crm_name = effective_crm_status_name(order)
        if crm_name:
            return crm_name
        crm_id = str(getattr(order, "crm_status_id", None) or "").strip()
        if crm_id:
            return f"CRM #{crm_id}"
    status = getattr(order, "status", None)
    return STATUS_LABELS.get(status, getattr(status, "value", str(status or "")))


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
