"""Customer card for the dashboard: who the buyer is, what they buy, how to
reach them. Statistics cover the customer's own Telegram profile.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import case, func, or_, select

from shop import models as m
from shop.entities import OrderStatus
from shop.services import order_business
from shop.services.commerce_workspace import channel_expression

CHANNELS = {"miniapp": "Mini App", "bot": "Бот", "unknown": "Невідомо"}


def _money(value) -> str:
    """Exact amount as a string: JSON floats would lose kopecks."""
    return str(Decimal(str(value or 0)).quantize(Decimal("0.01")))


async def summary(repo, user) -> dict:
    ids = [user.id]
    orders = m.Order.user_id.in_(ids)
    sale = m.Order.business_state == order_business.BUSINESS_SALE
    lost = or_(m.Order.business_state == order_business.BUSINESS_REFUSAL, m.Order.status == OrderStatus.CANCELLED)

    def count_if(condition):
        return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)
    row = (await repo.s.execute(select(
        func.count(m.Order.id), count_if(sale), func.coalesce(func.sum(case((sale, m.Order.total), else_=0)), 0),
        count_if(lost), func.min(m.Order.created_at), func.max(m.Order.created_at),
        func.coalesce(func.sum(case((~lost, m.Order.total), else_=0)), 0),
        count_if(~lost),
    ).where(orders))).one()
    total, sales, revenue, lost_count, first_at, last_at, ordered_sum, ordered_count = row
    channel = channel_expression()
    channels = [{"key": key, "label": CHANNELS.get(key, key), "orders": int(n)} for key, n in
                (await repo.s.execute(select(channel, func.count()).where(orders).group_by(channel)
                                      .order_by(func.count().desc()))).all()]
    kept = (m.Order.business_state != order_business.BUSINESS_REFUSAL) & (m.Order.status != OrderStatus.CANCELLED)
    category = func.coalesce(m.Category.name, "Без категорії")
    categories = [{"name": name, "qty": int(qty), "amount": _money(amount)} for name, qty, amount in
              (await repo.s.execute(select(category, func.sum(m.OrderItem.qty), func.sum(m.OrderItem.qty * m.OrderItem.price))
                                    .join(m.Order, m.Order.id == m.OrderItem.order_id)
                                    .outerjoin(m.Product, m.Product.id == m.OrderItem.product_id)
                                    .outerjoin(m.Category, m.Category.id == m.Product.category_id)
                                    .where(orders, kept).group_by(category)
                                    .order_by(func.sum(m.OrderItem.qty).desc()).limit(5))).all()]
    products = [{"name": name, "qty": int(qty)} for name, qty in
                (await repo.s.execute(select(m.OrderItem.name, func.sum(m.OrderItem.qty))
                                      .join(m.Order, m.Order.id == m.OrderItem.order_id)
                                      .where(orders, kept).group_by(m.OrderItem.name)
                                      .order_by(func.sum(m.OrderItem.qty).desc()).limit(5))).all()]
    # Chats: order conversations (newest first) and general support threads.
    last_msg = func.max(m.OrderMessage.created_at)
    unread = func.coalesce(func.sum(case(((m.OrderMessage.direction == "in") & (m.OrderMessage.is_read.is_(False)), 1), else_=0)), 0)
    order_chats = [{"order_id": oid, "messages": int(n), "unread": int(u), "last_message_at": at} for oid, n, u, at in
                   (await repo.s.execute(select(m.OrderMessage.order_id, func.count(), unread, last_msg)
                                         .join(m.Order, m.Order.id == m.OrderMessage.order_id).where(orders)
                                         .group_by(m.OrderMessage.order_id).order_by(last_msg.desc()).limit(20))).all()]
    support = [{"id": t.id, "status": t.status, "created_at": t.created_at, "last_message_at": t.last_message_at,
                "closed_at": t.closed_at} for t in
               (await repo.s.scalars(select(m.SupportThread).where(m.SupportThread.user_id.in_(ids))
                                     .order_by(m.SupportThread.id.desc()).limit(20))).all()]
    sales = int(sales)
    return {
        "user_ids": ids,
        "telegram_connected": bool(user.tg_id and user.tg_id > 0),
        "stats": {
            "orders": int(total), "sales": sales, "lost": int(lost_count),
            "revenue": _money(revenue),
            "average_check": _money(Decimal(str(revenue)) / sales) if sales else None,
            "ordered_sum": _money(ordered_sum),
            "average_order": _money(Decimal(str(ordered_sum)) / int(ordered_count)) if int(ordered_count) else None,
            "first_order_at": first_at, "last_order_at": last_at,
            "bonus_balance": _money(user.bonus_balance),
        },
        "channels": channels, "categories": categories, "products": products,
        "order_chats": order_chats, "support_threads": support,
    }
