from __future__ import annotations

import math

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from shop.entities import User
from shop.repo.base import Repository

router = Router()
PAGE_SIZE = 8


async def _send_categories(target: Message | CallbackQuery, repo: Repository) -> None:
    items = await repo.list_categories(only_active=True)
    if not items:
        text, markup = "Каталог наповнюється. Зазирніть трохи пізніше.", None
    else:
        text, markup = "<b>Каталог</b>\n\nОберіть категорію:", kb.categories(items)

    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=markup)
        except Exception:
            await target.message.answer(text, reply_markup=markup)
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup)


@router.message(F.text == "🛍 Каталог")
async def catalog_message(message: Message, repo: Repository) -> None:
    await _send_categories(message, repo)


@router.callback_query(F.data == "catalog")
async def catalog_callback(callback: CallbackQuery, repo: Repository) -> None:
    await _send_categories(callback, repo)


async def _render_products(callback: CallbackQuery, repo: Repository, cat_id: int, page: int) -> None:
    category = await repo.get_category(cat_id)
    if not category:
        await callback.answer("Категорію не знайдено", show_alert=True)
        return

    total = await repo.count_products(cat_id, only_active=True)
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(0, min(page, pages - 1))

    items = await repo.list_products(
        category_id=cat_id, only_active=True, limit=PAGE_SIZE, offset=page * PAGE_SIZE
    )

    header = f"<b>{category.name}</b>"
    if category.description:
        header += f"\n{category.description}"
    if not items:
        header += "\n\nУ цій категорії поки порожньо."

    markup = kb.products(items, cat_id, page, pages)
    try:
        await callback.message.edit_text(header, reply_markup=markup)
    except Exception:
        await callback.message.answer(header, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("cat:"))
async def open_category(callback: CallbackQuery, repo: Repository) -> None:
    await _render_products(callback, repo, int(callback.data.split(":")[1]), 0)


@router.callback_query(F.data.startswith("catpage:"))
async def page_category(callback: CallbackQuery, repo: Repository) -> None:
    _, cat_id, page = callback.data.split(":")
    await _render_products(callback, repo, int(cat_id), int(page))


@router.callback_query(F.data.startswith("prod:"))
async def open_product(callback: CallbackQuery, repo: Repository, user: User) -> None:
    product_id = int(callback.data.split(":")[1])
    product = await repo.get_product(product_id)
    if not product or not product.is_active:
        await callback.answer("Товар більше недоступний", show_alert=True)
        return

    in_cart = next(
        (line.qty for line in await repo.get_cart(user.id) if line.product_id == product_id), 0
    )

    lines = [f"<b>{product.name}</b>"]
    if product.description:
        lines.append(product.description)
    if product.old_price and product.old_price > product.price:
        lines.append(f"\n<s>{product.old_price:.0f}</s> <b>{product.price:.0f} грн</b>")
    else:
        lines.append(f"\n<b>{product.price:.0f} грн</b>")
    lines.append("В наявності" if product.stock > 0 else "Немає в наявності")

    text = "\n".join(lines)
    markup = kb.product_card(product, in_cart)
    photo = product.photo_file_id or product.photo_url

    if photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer_photo(photo, caption=text, reply_markup=markup)
    else:
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except Exception:
            await callback.message.answer(text, reply_markup=markup)
    await callback.answer()
