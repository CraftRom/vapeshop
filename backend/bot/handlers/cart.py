from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards as kb
from bot import texts
from shop.models import User
from shop.services import cart as cart_service

router = Router()


def render(items) -> str:
    lines = ["<b>Кошик</b>\n"]
    total = 0
    for i in items:
        line_sum = i.product.price * i.qty
        total += line_sum
        lines.append(f"• {i.product.name}\n  {i.qty} × {i.product.price:.0f} = {line_sum:.0f} грн")
    lines.append(f"\n<b>Разом: {total:.0f} грн</b>")
    return "\n".join(lines)


async def _show(target: Message | CallbackQuery, session: AsyncSession, user: User) -> None:
    items = await cart_service.get_items(session, user.id)
    text = texts.CART_EMPTY if not items else render(items)
    markup = None if not items else kb.cart(items)

    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=markup)
        except Exception:
            await target.message.answer(text, reply_markup=markup)
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup)


@router.message(F.text == "🛒 Кошик")
async def cart_message(message: Message, session: AsyncSession, user: User) -> None:
    await _show(message, session, user)


@router.callback_query(F.data == "cart")
async def cart_callback(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    await _show(callback, session, user)


@router.callback_query(F.data.startswith("add:"))
async def add_to_cart(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    product_id = int(callback.data.split(":")[1])
    item = await cart_service.add(session, user.id, product_id, 1)
    if not item:
        await callback.answer("Не вдалося додати — перевірте наявність", show_alert=True)
        return
    await callback.answer("Додано в кошик")
    try:
        await callback.message.edit_reply_markup(reply_markup=kb.product_card(item.product, item.qty))
    except Exception:
        pass


@router.callback_query(F.data.startswith("cartqty:"))
async def change_qty(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    _, product_id, qty = callback.data.split(":")
    await cart_service.set_qty(session, user.id, int(product_id), int(qty))
    await _show(callback, session, user)


@router.callback_query(F.data == "cartclear")
async def clear_cart(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    await cart_service.clear(session, user.id)
    await callback.message.edit_text(texts.CART_EMPTY)
    await callback.answer("Кошик очищено")
