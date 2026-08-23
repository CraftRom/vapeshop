"""Листування оператора з клієнтом у межах замовлення.

Ключова складність — у клієнта може бути кілька відкритих замовлень
одночасно, а в Telegram у нього один чат із ботом. Тому кожне повідомлення
оператора йде з підписом «Замовлення №N» і з ForceReply: відповідь клієнта
несе reply_to_message_id, за яким ми однозначно знаходимо потрібне
замовлення. Якщо клієнт пише не відповіддю, бот перепитує кнопками.
"""
from __future__ import annotations

import logging
from html import escape

from aiogram.types import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup

from shop.entities import Order, OrderStatus
from shop.repo.base import Repository

log = logging.getLogger(__name__)

# Статуси, за яких листування ще має сенс. Виконане чи скасоване
# замовлення закривається — інакше стрічка ніколи не порожніє.
OPEN_STATUSES = (
    OrderStatus.NEW, OrderStatus.CONFIRMED, OrderStatus.PAID, OrderStatus.SHIPPED,
)


def esc(value) -> str:
    return escape(str(value or ""), quote=False)


def _header(order_id: int) -> str:
    return f"💬 <b>Замовлення №{order_id}</b>"


async def send_to_client(
    bot, repo: Repository, order: Order, text: str, author: str = ""
) -> bool:
    """Повідомлення оператора клієнту. Зберігає його в стрічці замовлення."""
    user = order.user or await repo.get_user(order.user_id)
    if not user:
        log.warning("Замовлення №%s без клієнта — нікому писати", order.id)
        return False

    signature = f"\n\n<i>{esc(author)}</i>" if author else ""
    try:
        sent = await bot.send_message(
            user.tg_id,
            f"{_header(order.id)}\n\n{esc(text)}{signature}",
            # ForceReply відкриває поле з цитатою: відповідь клієнта
            # гарантовано принесе reply_to_message
            reply_markup=ForceReply(input_field_placeholder=f"Відповідь щодо №{order.id}"),
        )
    except Exception:
        log.warning("Не вдалося доставити повідомлення клієнту (замовлення №%s)",
                    order.id, exc_info=True)
        return False

    await repo.add_order_message({
        "order_id": order.id, "user_id": order.user_id, "direction": "out",
        "author": author, "text": text, "tg_message_id": sent.message_id,
        "is_read": True,
    })
    return True


async def send_tracking(bot, repo: Repository, order: Order, tracking: str) -> bool:
    """Повідомляє ТТН. Окремий текст, бо це найочікуваніше повідомлення."""
    user = order.user or await repo.get_user(order.user_id)
    if not user:
        return False

    text = (
        f"📦 <b>Замовлення №{order.id} відправлено</b>\n\n"
        f"Номер накладної:\n<code>{esc(tracking)}</code>\n\n"
        "Натисніть на номер, щоб скопіювати."
    )
    try:
        sent = await bot.send_message(user.tg_id, text)
    except Exception:
        log.warning("Не вдалося надіслати ТТН по замовленню №%s", order.id, exc_info=True)
        return False

    await repo.add_order_message({
        "order_id": order.id, "user_id": order.user_id, "direction": "out",
        "author": "Система", "text": f"Відправлено. ТТН: {tracking}",
        "tg_message_id": sent.message_id, "is_read": True,
    })
    return True


async def open_orders_for(repo: Repository, user_id: int) -> list[Order]:
    """Замовлення клієнта, у межах яких листування ще актуальне."""
    orders = await repo.list_orders(user_id=user_id, limit=20)
    return [o for o in orders if o.status in OPEN_STATUSES]


async def route_incoming(repo: Repository, user, message) -> int | None:
    """Визначає, до якого замовлення належить повідомлення клієнта.

    Порядок: явна відповідь на повідомлення бота → єдине відкрите
    замовлення → None, якщо вибір неоднозначний.
    """
    reply_to = getattr(message, "reply_to_message", None)
    if reply_to is not None:
        order_id = await repo.find_order_by_tg_message(reply_to.message_id)
        if order_id:
            return order_id

    open_orders = await open_orders_for(repo, user.id)
    if len(open_orders) == 1:
        return open_orders[0].id
    return None


def pick_order_keyboard(orders: list[Order]) -> InlineKeyboardMarkup:
    """Кнопки вибору замовлення, коли їх кілька."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"№{o.id} · {o.total:.0f} · {o.created_at:%d.%m}" if o.created_at
                 else f"№{o.id} · {o.total:.0f}",
            callback_data=f"chat:{o.id}",
        )]
        for o in orders[:8]
    ])


async def save_incoming(
    repo: Repository, order: Order, user, text: str, bot=None
) -> None:
    """Зберігає відповідь клієнта і сповіщає команду.

    Без сповіщення оператор дізнався б про повідомлення лише випадково,
    відкривши панель. Клієнт при цьому чекає на відповідь.
    """
    await repo.add_order_message({
        "order_id": order.id, "user_id": user.id, "direction": "in",
        "author": user.first_name or user.username or f"id{user.tg_id}",
        "text": text, "tg_message_id": None, "is_read": False,
    })

    if bot is None:
        return

    from shop.services.shop_settings import get_shop_settings

    shop = await get_shop_settings(repo)
    if not shop.admin_chat_id:
        return

    who = f"@{esc(user.username)}" if user.username else esc(user.first_name or "клієнт")
    try:
        await bot.send_message(
            shop.admin_chat_id,
            f"💬 <b>Питання по замовленню №{order.id}</b>\n"
            f"Від: {who}\n\n{esc(text)}\n\n"
            "<i>Відповісти — у панелі, на сторінці замовлення.</i>",
        )
    except Exception:
        log.info("Не вдалося сповістити команду про повідомлення клієнта", exc_info=True)
