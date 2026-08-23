"""Листування оператора з клієнтом у межах замовлення.

Ключова складність — у клієнта може бути кілька відкритих замовлень
одночасно, а в Telegram у нього один чат із ботом. Тому кожне повідомлення
оператора йде з підписом «Замовлення №N» і з ForceReply: відповідь клієнта
несе reply_to_message_id, за яким ми однозначно знаходимо потрібне
замовлення. Якщо клієнт пише не відповіддю, бот перепитує кнопками.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from html import escape

from aiogram.types import (
    ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo,
)

from shop.entities import Order, OrderStatus
from shop.repo.base import Repository

log = logging.getLogger(__name__)

# Статуси, за яких листування триває без обмежень.
OPEN_STATUSES = (
    OrderStatus.NEW, OrderStatus.CONFIRMED, OrderStatus.ACCEPTED,
    OrderStatus.PAID, OrderStatus.SHIPPED,
)

# Скільки днів після закриття замовлення розмова ще доступна.
# Без цього клієнт, який щойно отримав посилку і хоче щось уточнити,
# упирався б у «немає активних замовлень» — саме тоді, коли питання
# найімовірніші: недостача, брак, повернення.
CLOSED_GRACE_DAYS = 7


def esc(value) -> str:
    return escape(str(value or ""), quote=False)


def _header(order_id: int) -> str:
    return f"💬 <b>Замовлення №{order_id}</b>"


def chat_keyboard(order_id: int) -> InlineKeyboardMarkup | None:
    """Кнопка, що відкриває вітрину одразу на чаті цього замовлення.

    Без адреси сайту кнопку не побудувати — тоді клієнт просто відповідає
    в чаті з ботом, і це теж робочий шлях.
    """
    from shop.services.shop_settings import current

    public_url = (current().public_url or "").rstrip("/")
    if not public_url.startswith("https://"):
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(
            text="💬 Відкрити чат",
            web_app=WebAppInfo(url=f"{public_url}/app/?chat={order_id}"),
        )
    ]])


async def announce_accepted(bot, repo: Repository, order: Order, operator_name: str) -> bool:
    """Повідомляє, хто саме взяв замовлення в роботу.

    Знеособлене «статус змінено» нічого не дає клієнту. Ім'я оператора
    перетворює це на початок розмови з конкретною людиною.
    """
    user = order.user or await repo.get_user(order.user_id)
    if not user:
        return False

    who = esc(operator_name) or "Наш оператор"
    text = (
        f"✅ <b>Замовлення №{order.id} прийнято в роботу</b>\n\n"
        f"Ним займається {who}.\n"
        "Питання щодо доставки чи оплати пишіть прямо сюди — "
        "відповідь надійде в цей чат."
    )
    try:
        sent = await bot.send_message(user.tg_id, text, reply_markup=chat_keyboard(order.id))
    except Exception:
        log.warning("Не вдалося повідомити про прийняття №%s", order.id, exc_info=True)
        return False

    await repo.add_order_message({
        "order_id": order.id, "user_id": order.user_id, "direction": "out",
        "author": "Система", "text": f"Замовлення прийняв {operator_name}",
        "tg_message_id": sent.message_id, "is_read": True,
    })
    return True


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
        # Кнопка вітрини корисніша за ForceReply: у ній видно всю історію
        # саме цього замовлення. ForceReply лишається запасним шляхом, коли
        # адреса сайту не налаштована.
        markup = chat_keyboard(order.id) or ForceReply(
            input_field_placeholder=f"Відповідь щодо №{order.id}"
        )
        sent = await bot.send_message(
            user.tg_id,
            f"{_header(order.id)}\n\n{esc(text)}{signature}",
            reply_markup=markup,
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
        sent = await bot.send_message(user.tg_id, text, reply_markup=chat_keyboard(order.id))
    except Exception:
        log.warning("Не вдалося надіслати ТТН по замовленню №%s", order.id, exc_info=True)
        return False

    await repo.add_order_message({
        "order_id": order.id, "user_id": order.user_id, "direction": "out",
        "author": "Система", "text": f"Відправлено. ТТН: {tracking}",
        "tg_message_id": sent.message_id, "is_read": True,
    })
    return True


def is_chattable(order: Order) -> bool:
    """Чи можна ще писати щодо цього замовлення."""
    if order.status in OPEN_STATUSES:
        return True
    if not order.created_at:
        return False
    closed_for = datetime.now(order.created_at.tzinfo) - order.created_at
    return closed_for <= timedelta(days=CLOSED_GRACE_DAYS)


async def send_tracking_update(bot, repo: Repository, order: Order, tracking: str) -> bool:
    """Накладну виправили вже після відправлення.

    Мовчазна заміна лишила б клієнта зі старим номером, за яким посилка
    не знаходиться — і він вважав би, що її не відправили.
    """
    user = order.user or await repo.get_user(order.user_id)
    if not user:
        return False
    try:
        sent = await bot.send_message(
            user.tg_id,
            f"📦 <b>Замовлення №{order.id}: накладну оновлено</b>\n\n"
            f"Новий номер:\n<code>{esc(tracking)}</code>\n\n"
            "Попередній номер більше не актуальний.",
            reply_markup=chat_keyboard(order.id),
        )
    except Exception:
        log.warning("Не вдалося повідомити про заміну ТТН №%s", order.id, exc_info=True)
        return False

    await repo.add_order_message({
        "order_id": order.id, "user_id": order.user_id, "direction": "out",
        "author": "Система", "text": f"Накладну змінено на {tracking}",
        "tg_message_id": sent.message_id, "is_read": True,
    })
    return True


async def open_orders_for(repo: Repository, user_id: int) -> list[Order]:
    """Усе, про що ще можна писати — разом із закритими в межах грейс-періоду.

    Використовується для показу списку й вибору кнопкою.
    """
    orders = await repo.list_orders(user_id=user_id, limit=20)
    return [o for o in orders if is_chattable(o)]


async def active_orders_for(repo: Repository, user_id: int) -> list[Order]:
    """Лише незакриті замовлення — для автовизначення адресата.

    Грейс-період навмисно не враховується: інакше щойно виконане замовлення
    робило б вибір неоднозначним, і клієнта питали б кнопками навіть тоді,
    коли активне замовлення в нього одне.
    """
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

    # Замовлення, яке клієнт обрав кнопкою. Зберігається в базі, тож
    # переживає холодний старт функції — на відміну від стану FSM.
    # Дозволяємо й закриті в межах грейс-періоду: клієнт міг свідомо
    # обрати щойно виконане, щоб уточнити щось по ньому.
    chattable = {o.id for o in await open_orders_for(repo, user.id)}
    if user.chat_order_id in chattable:
        return user.chat_order_id

    active = await active_orders_for(repo, user.id)
    if len(active) == 1:
        return active[0].id
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


def describe_attachment(message) -> dict | None:
    """Витягує вкладення з повідомлення Telegram.

    Зберігаємо лише file_id: сам файл лишається у Telegram, панель тягне
    його через бекенд і тільки коли оператор відкриває стрічку.
    """
    if getattr(message, "photo", None):
        # Останній елемент — найбільший доступний розмір
        return {"file_id": message.photo[-1].file_id, "file_kind": "photo",
                "file_name": "Фото"}
    if getattr(message, "document", None):
        return {"file_id": message.document.file_id, "file_kind": "document",
                "file_name": message.document.file_name or "Документ"}
    if getattr(message, "video", None):
        return {"file_id": message.video.file_id, "file_kind": "video",
                "file_name": "Відео"}
    if getattr(message, "voice", None):
        return {"file_id": message.voice.file_id, "file_kind": "voice",
                "file_name": "Голосове"}
    return None


async def save_incoming(
    repo: Repository, order: Order, user, text: str, bot=None, attachment: dict | None = None
) -> None:
    """Зберігає відповідь клієнта і сповіщає команду.

    Без сповіщення оператор дізнався б про повідомлення лише випадково,
    відкривши панель. Клієнт при цьому чекає на відповідь.
    """
    await repo.add_order_message({
        "order_id": order.id, "user_id": user.id, "direction": "in",
        "author": user.first_name or user.username or f"id{user.tg_id}",
        "text": text, "tg_message_id": None, "is_read": False,
        **(attachment or {}),
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
