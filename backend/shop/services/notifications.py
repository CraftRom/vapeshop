"""Сповіщення про замовлення.

Винесено зі скриптів бота, бо замовлення надходять із двох місць: із чату
й з вітрини Mini App. Поки цей код жив лише в обробнику бота, замовлення,
оформлені у вітрині, не доходили до менеджера взагалі.

Усе, що ввів користувач, екранується. Telegram працює в режимі HTML, і
незакритий кутовий дужок у чиємусь імені або коментарі змушує його
відхилити повідомлення цілком — тобто магазин мовчки втрачав би сповіщення
про замовлення. Екранування також не дає підсунути менеджеру посилання
під виглядом коментаря до замовлення.
"""
from __future__ import annotations

import logging
from html import escape

from shop.config import settings
from shop.entities import Order, User
from shop.repo.base import Repository
from shop.services.shop_settings import get_shop_settings

def topic_kwargs(topic_id: int) -> dict:
    """Аргументи адресації в гілку форуму.

    Порожній словник, якщо гілка не задана: message_thread_id=0 Telegram
    відхиляє помилкою, а None у деяких версіях aiogram теж. Простіше не
    передавати параметр узагалі.
    """
    return {"message_thread_id": topic_id} if topic_id else {}


log = logging.getLogger(__name__)

PAYMENT_LABELS = {"card": "картка", "cod": "накладений платіж"}


def esc(value) -> str:
    """Робить рядок безпечним для HTML-розмітки Telegram."""
    return escape(str(value or ""), quote=False)


async def build_order_text(repo: Repository, order: Order, user: User) -> str:
    shop = await get_shop_settings(repo)
    cur = esc(shop.currency)

    items = "\n".join(
        f"• {esc(ln.name)} × {ln.qty} — {ln.line_total:.0f} {cur}" for ln in order.items
    )
    who = f"@{esc(user.username)}" if user.username else f"id{user.tg_id}"

    text = (
        f"🆕 <b>Замовлення №{order.id}</b>\n\n"
        f"{items}\n\n"
        f"Сума: {order.subtotal:.0f} {cur}\n"
        f"Знижка: {order.discount:.0f} {cur} | Бонуси: {order.bonus_used:.0f} {cur}\n"
        f"<b>До сплати: {order.total:.0f} {cur}</b>\n\n"
        f"Клієнт: {esc(order.contact_name)} ({who})\n"
        f"Телефон: {esc(order.contact_phone)}\n"
        f"Доставка: {esc(order.delivery_city)}, {esc(order.delivery_address)}\n"
        f"Оплата: {PAYMENT_LABELS.get(order.payment_method, esc(order.payment_method))}"
    )
    if order.comment:
        text += f"\n\nКоментар: {esc(order.comment)}"
    return text


async def notify_new_order(bot, repo: Repository, order: Order, user: User) -> bool:
    """Надсилає замовлення в адмінський чат. Повертає, чи вдалося.

    Помилка тут не має валити оформлення: замовлення вже в базі й видиме
    в панелі. Але вона потрапляє в лог як попередження, бо означає, що
    менеджер про замовлення не дізнався.
    """
    shop = await get_shop_settings(repo)
    if not shop.admin_chat_id:
        log.warning("Чат для замовлень не заданий — №%s нікуди надіслати", order.id)
        return False

    from bot import keyboards as kb

    try:
        await bot.send_message(
            shop.admin_chat_id,
            await build_order_text(repo, order, user),
            reply_markup=kb.admin_order(order.id),
            **topic_kwargs(shop.admin_topic_id),
        )
        return True
    except Exception:
        log.warning("Не вдалося надіслати замовлення №%s в адмінський чат",
                    order.id, exc_info=True)
        return False
