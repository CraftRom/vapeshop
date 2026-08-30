from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from shop.config import settings
from shop.services.shop_settings import current, get_shop_settings
from shop.entities import STATUS_LABELS, OrderStatus
from shop.repo.base import Repository
from shop.services.shop_service import change_order_status

import logging

log = logging.getLogger("bot.admin")

router = Router()


class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        # Список редагується з панелі; .env лишається дефолтом
        return event.from_user.id in current().admin_id_list


router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())


@router.message(Command("stats"))
async def stats(message: Message, repo: Repository) -> None:
    # Лише в адмінському чаті. Раніше вистачало бути в ADMIN_IDS, і власник,
    # покликавши /stats у сторонній групі, вивалив би туди виручку магазину
    # перед усіма присутніми.
    if message.chat.id != current().admin_chat_id:
        log.info("Спроба /stats поза адмінським чатом: %s", message.chat.id)
        return

    summary = await repo.stats_summary(30)
    shop = await get_shop_settings(repo)
    await message.answer(
        f"<b>Коротка статистика</b>\n\n"
        f"Клієнтів: {summary.customers_total}\n"
        f"Нових замовлень: {summary.orders_new}\n"
        f"Виручка: {summary.revenue_total:.0f} {shop.currency}\n"
        f"Товарів із залишком &lt; 5: {summary.low_stock}\n\n"
        f"Повна аналітика — у дашборді."
    )


@router.callback_query(F.data.startswith("ao:"))
async def admin_change_status(callback: CallbackQuery, repo: Repository) -> None:
    # Дані кнопки приходять ззовні: зіпсований рядок не має валити обробник
    try:
        _, raw_id, status_value = callback.data.split(":")
        order_id = int(raw_id)
        status = OrderStatus(status_value)
    except ValueError:
        await callback.answer("Кнопка застаріла, оновіть повідомлення", show_alert=True)
        return

    order = await repo.get_order(order_id)
    if not order:
        await callback.answer("Замовлення не знайдено", show_alert=True)
        return
    reward = await change_order_status(repo, order, status)
    label = STATUS_LABELS[status]

    await callback.answer(f"Статус: {label}")
    try:
        await callback.message.edit_reply_markup(reply_markup=kb.admin_order(order.id))
    except Exception:
        pass

    client = await repo.get_user(order.user_id)
    if not client:
        return

    try:
        await callback.bot.send_message(
            client.tg_id, f"Замовлення №{order.id}: статус змінено на «{label}»."
        )
    except Exception:
        pass

    if reward and client.referrer_id:
        shop = await get_shop_settings(repo)
        referrer = await repo.get_user(client.referrer_id)
        if referrer:
            try:
                await callback.bot.send_message(
                    referrer.tg_id,
                    f"🎁 Вам нараховано {reward:.0f} {shop.currency} бонусів "
                    f"за замовлення запрошеного друга.",
                )
            except Exception:
                pass
