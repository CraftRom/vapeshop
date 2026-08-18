from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards as kb
from shop.config import settings
from shop.models import Order, OrderStatus, Product, User
from shop.services.orders import STATUS_LABELS, change_status

router = Router()


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        return event.from_user.id in settings.admin_id_list


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.message(Command("stats"))
async def stats(message: Message, session: AsyncSession) -> None:
    users_total = await session.scalar(select(func.count(User.id)))
    orders_new = await session.scalar(
        select(func.count(Order.id)).where(Order.status == OrderStatus.NEW)
    )
    revenue = await session.scalar(
        select(func.coalesce(func.sum(Order.total), 0)).where(
            Order.status.in_([OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DONE])
        )
    )
    low_stock = await session.scalar(
        select(func.count(Product.id)).where(Product.is_active.is_(True), Product.stock < 5)
    )
    await message.answer(
        f"<b>Коротка статистика</b>\n\n"
        f"Клієнтів: {users_total}\n"
        f"Нових замовлень: {orders_new}\n"
        f"Виручка: {revenue:.0f} {settings.currency}\n"
        f"Товарів із залишком &lt; 5: {low_stock}\n\n"
        f"Повна аналітика — у дашборді."
    )


@router.callback_query(F.data.startswith("ao:"))
async def admin_change_status(callback: CallbackQuery, session: AsyncSession) -> None:
    _, order_id, status_value = callback.data.split(":")
    order = await session.get(Order, int(order_id))
    if not order:
        await callback.answer("Замовлення не знайдено", show_alert=True)
        return

    status = OrderStatus(status_value)
    reward = await change_status(session, order, status)
    label = STATUS_LABELS[status]

    await callback.answer(f"Статус: {label}")
    try:
        await callback.message.edit_reply_markup(reply_markup=kb.admin_order(order.id))
    except Exception:
        pass

    client = await session.get(User, order.user_id)
    if client:
        try:
            await callback.bot.send_message(
                client.tg_id, f"Замовлення №{order.id}: статус змінено на «{label}»."
            )
        except Exception:
            pass

        if reward and client.referrer_id:
            referrer = await session.get(User, client.referrer_id)
            if referrer:
                try:
                    await callback.bot.send_message(
                        referrer.tg_id,
                        f"🎁 Вам нараховано {reward:.0f} {settings.currency} бонусів "
                        f"за замовлення запрошеного друга.",
                    )
                except Exception:
                    pass
