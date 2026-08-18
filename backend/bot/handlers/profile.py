from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards as kb
from shop.config import settings
from shop.models import Order, User
from shop.services.orders import STATUS_LABELS
from shop.services.users import user_stats

router = Router()


def referral_link(code: str) -> str:
    return f"https://t.me/{settings.bot_username}?start={code}"


@router.message(F.text == "👤 Профіль")
async def profile(message: Message, session: AsyncSession, user: User) -> None:
    stats = await user_stats(session, user.id)
    link = referral_link(user.referral_code)

    text = (
        f"<b>Ваш профіль</b>\n\n"
        f"Замовлень: {stats['orders_count']}\n"
        f"Витрачено: {stats['total_spent']:.0f} {settings.currency}\n"
        f"Бонусний рахунок: <b>{user.bonus_balance:.0f} {settings.currency}</b>\n\n"
        f"<b>Реферальна програма</b>\n"
        f"Запрошено друзів: {stats['referrals']}\n"
        f"Ви отримуєте {settings.referral_percent:.0f}% бонусами від кожного "
        f"виконаного замовлення запрошеного друга. Бонусами можна оплатити "
        f"до {settings.bonus_max_percent:.0f}% вартості замовлення.\n\n"
        f"Ваше посилання:\n<code>{link}</code>"
    )
    await message.answer(text, reply_markup=kb.profile(link))


@router.callback_query(F.data == "myorders")
async def my_orders(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    orders = list(
        await session.scalars(
            select(Order).where(Order.user_id == user.id).order_by(Order.created_at.desc()).limit(10)
        )
    )
    if not orders:
        await callback.answer("У вас поки немає замовлень", show_alert=True)
        return

    lines = ["<b>Останні замовлення</b>\n"]
    for o in orders:
        items = ", ".join(f"{i.name} ×{i.qty}" for i in o.items)
        lines.append(
            f"<b>№{o.id}</b> — {STATUS_LABELS.get(o.status, o.status.value)}\n"
            f"{o.created_at:%d.%m.%Y} · {o.total:.0f} {settings.currency}\n"
            f"<i>{items}</i>\n"
        )
    await callback.message.answer("\n".join(lines))
    await callback.answer()
