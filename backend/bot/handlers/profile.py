from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from shop.config import settings
from shop.services.shop_settings import get_shop_settings
from shop.entities import STATUS_LABELS, User
from shop.repo.base import Repository

router = Router()


def referral_link(code: str) -> str:
    return f"https://t.me/{settings.bot_username}?start={code}"


@router.message(F.text == "👤 Профіль")
async def profile(message: Message, repo: Repository, user: User) -> None:
    fresh = await repo.get_user(user.id) or user
    link = referral_link(fresh.referral_code)

    shop = await get_shop_settings(repo)
    text = (
        f"<b>Ваш профіль</b>\n\n"
        f"Замовлень: {fresh.orders_count}\n"
        f"Витрачено: {fresh.total_spent:.0f} {shop.currency}\n"
        f"Бонусний рахунок: <b>{fresh.bonus_balance:.0f} {shop.currency}</b>\n\n"
        f"<b>Реферальна програма</b>\n"
        f"Запрошено друзів: {fresh.referrals_count}\n"
        f"Ви отримуєте {shop.referral_percent:.0f}% бонусами від кожного "
        f"виконаного замовлення запрошеного друга. Бонусами можна оплатити "
        f"до {shop.bonus_max_percent:.0f}% вартості замовлення.\n\n"
        f"Ваше посилання:\n<code>{link}</code>"
    )
    await message.answer(text, reply_markup=kb.profile(link))


@router.callback_query(F.data == "myorders")
async def my_orders(callback: CallbackQuery, repo: Repository, user: User) -> None:
    orders = await repo.list_orders(user_id=user.id, limit=10)
    if not orders:
        await callback.answer("У вас поки немає замовлень", show_alert=True)
        return

    shop = await get_shop_settings(repo)
    lines = ["<b>Останні замовлення</b>\n"]
    for order in orders:
        items = ", ".join(f"{ln.name} ×{ln.qty}" for ln in order.items)
        lines.append(
            f"<b>№{order.id}</b> — {STATUS_LABELS.get(order.status, order.status.value)}\n"
            f"{order.created_at:%d.%m.%Y} · {order.total:.0f} {shop.currency}\n"
            f"<i>{items}</i>\n"
        )
    await callback.message.answer("\n".join(lines))
    await callback.answer()
