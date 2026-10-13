"""Shared order conversation policy, independent of delivery channel."""
from datetime import datetime, timedelta, timezone

from shop.entities import OrderStatus
from shop.services import order_business as business

OPEN_STATUSES = (OrderStatus.NEW, OrderStatus.CONFIRMED, OrderStatus.ACCEPTED,
                 OrderStatus.PAID, OrderStatus.SHIPPED)
CLOSED_GRACE_DAYS = 7


def aware(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def is_closed(order):
    if business.has_crm_authority(order):
        return business.derive_business_state(order) in (business.BUSINESS_SALE, business.BUSINESS_REFUSAL)
    return order.status in (OrderStatus.DONE, OrderStatus.CANCELLED)


def chat_until(order):
    completed = getattr(order, "completed_at", None)
    return aware(completed) + timedelta(days=CLOSED_GRACE_DAYS) if is_closed(order) and completed else None


def can_chat(order, now=None):
    if not is_closed(order):
        return True
    until = chat_until(order)
    return bool(until and aware(now or datetime.now(timezone.utc)) < until)


def record_completion(order, was_closed, now=None):
    """Repeated metadata/CRM refreshes cannot extend the grace period."""
    if not is_closed(order):
        order.completed_at = None
    elif not was_closed:
        order.completed_at = now or datetime.now(timezone.utc)
