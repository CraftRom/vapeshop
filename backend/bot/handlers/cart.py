from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from bot import texts
from shop.entities import User
from shop.repo.base import Repository
from shop.services import shop_service as svc

router = Router()


def render(lines) -> str:
    out = ["<b>Кошик</b>\n"]
    total = Decimal(0)
    for line in lines:
        total += line.line_total
        out.append(
            f"• {line.product.name}\n  {line.qty} × {line.product.price:.0f} "
            f"= {line.line_total:.0f} грн"
        )
    out.append(f"\n<b>Разом: {total:.0f} грн</b>")
    return "\n".join(out)


async def _show(target: Message | CallbackQuery, repo: Repository, user: User) -> None:
    lines = await repo.get_cart(user.id)
    text = texts.CART_EMPTY if not lines else render(lines)
    markup = None if not lines else kb.cart(lines)

    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=markup)
        except Exception:
            await target.message.answer(text, reply_markup=markup)
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup)


@router.message(F.text == "🛒 Кошик")
async def cart_message(message: Message, repo: Repository, user: User) -> None:
    await _show(message, repo, user)


@router.callback_query(F.data == "cart")
async def cart_callback(callback: CallbackQuery, repo: Repository, user: User) -> None:
    await _show(callback, repo, user)


@router.callback_query(F.data.startswith("add:"))
async def add_to_cart(callback: CallbackQuery, repo: Repository, user: User) -> None:
    product_id = int(callback.data.split(":")[1])
    qty = await svc.add_to_cart(repo, user.id, product_id, 1)
    if not qty:
        await callback.answer("Не вдалося додати — перевірте наявність", show_alert=True)
        return
    await callback.answer("Додано в кошик")
    product = await repo.get_product(product_id)
    try:
        await callback.message.edit_reply_markup(reply_markup=kb.product_card(product, qty))
    except Exception:
        pass


@router.callback_query(F.data.startswith("cartqty:"))
async def change_qty(callback: CallbackQuery, repo: Repository, user: User) -> None:
    _, product_id, qty = callback.data.split(":")
    product = await repo.get_product(int(product_id))
    capped = min(int(qty), product.stock) if product else 0
    await repo.set_cart_qty(user.id, int(product_id), capped)
    await _show(callback, repo, user)


@router.callback_query(F.data == "cartclear")
async def clear_cart(callback: CallbackQuery, repo: Repository, user: User) -> None:
    await repo.clear_cart(user.id)
    await callback.message.edit_text(texts.CART_EMPTY)
    await callback.answer("Кошик очищено")
