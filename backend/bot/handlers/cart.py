from __future__ import annotations

from shop.formatting import money as format_money

from decimal import Decimal
from html import escape
from aiogram.exceptions import TelegramBadRequest
from shop.telegram_text import units, MESSAGE_LIMIT

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from bot import texts
from shop.entities import User
from shop.repo.base import Repository
from shop.services import shop_service as svc

router = Router()


def render(lines, *, total=None, start=0) -> str:
    out = ["<b>Кошик</b>\n"]
    total = sum((line.line_total for line in lines), Decimal(0)) if total is None else total
    for index, line in enumerate(lines, start + 1):
        out.append(
            f"{index}. {escape(line.product.name)}\n  {line.qty} × {format_money(line.product.price)} "
            f"= {format_money(line.line_total)} грн"
        )
    out.append(f"\n<b>Разом: {format_money(total)} грн</b>")
    return "\n".join(out)


def pages_for(lines):
    """Limit both text and keyboard growth; totals always cover the whole cart."""
    total = sum((line.line_total for line in lines), Decimal(0))
    pages, page, start = [], [], 0
    for line in lines:
        if page and (len(page) >= 8 or units(render([*page, line], total=total, start=start)) > MESSAGE_LIMIT - 100):
            pages.append((start, page))
            start += len(page)
            page = []
        page.append(line)
    if page:
        pages.append((start, page))
    return pages, total


async def _show(target: Message | CallbackQuery, repo: Repository, user: User, page=0) -> None:
    lines = await repo.get_cart(user.id)
    pages, total = pages_for(lines)
    if pages:
        page = max(0, min(page, len(pages) - 1))
        start, visible = pages[page]
        text = render(visible, total=total, start=start) + f"\n\nСторінка {page + 1}/{len(pages)} · позицій: {len(lines)}"
        markup = kb.cart(visible, page=page, pages=len(pages))
    else:
        text, markup = texts.CART_EMPTY, None
    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=markup)
        except TelegramBadRequest as exc:
            if "message is not modified" not in str(exc).lower():
                await target.message.answer(text, reply_markup=markup)
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup)


@router.callback_query(F.data.startswith("cartpage:"))
async def cart_page(callback: CallbackQuery, repo: Repository, user: User):
    try:
        page = max(0, int(callback.data.split(":")[1]))
    except (ValueError, IndexError):
        await callback.answer("Кнопка застаріла", show_alert=True)
        return
    await _show(callback, repo, user, page)


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
        await callback.message.edit_reply_markup(reply_markup=kb.product_card(product, qty, details=bool(product.description)))
    except Exception:
        pass


@router.callback_query(F.data.startswith("cartqty:"))
async def change_qty(callback: CallbackQuery, repo: Repository, user: User) -> None:
    try:
        _, product_id, qty, *extra = callback.data.split(":")
        product_id, qty = int(product_id), max(0, int(qty))
        page = max(0, int(extra[0])) if extra else 0
    except (ValueError, IndexError):
        await callback.answer("Кнопка застаріла", show_alert=True)
        return
    product = await repo.get_product(int(product_id))
    capped = min(int(qty), product.stock) if product else 0
    await repo.set_cart_qty(user.id, int(product_id), capped)
    await _show(callback, repo, user, page)


@router.callback_query(F.data == "cartclear")
async def clear_cart(callback: CallbackQuery, repo: Repository, user: User) -> None:
    await repo.clear_cart(user.id)
    await callback.message.edit_text(texts.CART_EMPTY)
    await callback.answer("Кошик очищено")
