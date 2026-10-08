from __future__ import annotations

import math
from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot import keyboards as kb
from shop.entities import User
from shop.repo.base import Repository

router = Router()
PAGE_SIZE = 8


async def _send_categories(target: Message | CallbackQuery, repo: Repository) -> None:
    items = await repo.list_categories(only_active=True)
    subs = await repo.list_subcategories(only_active=True)
    text, markup = "<b>Каталог</b>\n\nОберіть розділ:", kb.categories(items, [s for s in subs if s.category_id is None])

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


async def _render_products(callback, repo, cat_id=None, page=0, scope=None):
    scope = scope or f"cat:{cat_id}"
    kind, value = scope.split(":")
    filters = {}; children = []; category = None
    if kind in {"cat", "sub", "root"}:
        if kind == "root":
            category = await repo.get_category(int(value))
            filters['category_id'] = int(value)
            children = await repo.list_subcategories(category_id=int(value), only_active=True)
        else:
            # Old cat buttons refer to categories migrated into subcategories.
            category = await repo.get_subcategory(int(value))
            filters['subcategory_id'] = int(value)
        if not category or not category.is_active:
            await callback.answer("Розділ недоступний", show_alert=True)
            return
        header = f"<b>{escape(category.name)}</b>"
        if category.description: header += f"\n{escape(category.description)}"
    else:
        header = {'all':'<b>Усі товари</b>','new':'<b>Новинки</b>','sale':'<b>Акції</b>'}.get(value, '<b>Каталог</b>')
        if value == 'new': filters['is_new'] = True
        if value == 'sale': filters['is_sale'] = True
    total = await repo.count_products(only_active=True, **filters)
    pages = max(1, math.ceil(total/PAGE_SIZE)); page=max(0,min(page,pages-1))
    items=await repo.list_products(only_active=True, limit=PAGE_SIZE, offset=page*PAGE_SIZE, **filters)
    if not items: header += "\n\nТоварів поки немає."
    markup=kb.products(items, cat_id, page, pages, scope=scope, children=children)
    try: await callback.message.edit_text(header, reply_markup=markup)
    except Exception: await callback.message.answer(header, reply_markup=markup)
    await callback.answer()


@router.callback_query(F.data.startswith("cat:") | F.data.startswith("root:") | F.data.startswith("sub:") | F.data.startswith("shelf:"))
async def open_category(callback: CallbackQuery, repo: Repository):
    await _render_products(callback, repo, scope=callback.data)


@router.callback_query(F.data.startswith("catpage:") | F.data.startswith("browse:"))
async def page_category(callback: CallbackQuery, repo: Repository):
    parts=callback.data.split(":")
    scope=f"cat:{parts[1]}" if parts[0]=='catpage' else ':'.join(parts[1:-1])
    await _render_products(callback, repo, page=int(parts[-1]), scope=scope)


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

    lines = [f"<b>{escape(product.name)}</b>", f"Артикул: <code>{escape(product.sku)}</code>"]
    if product.is_new: lines.append("Новинка")
    if product.is_sale: lines.append("Акція")
    if product.description:
        lines.append(escape(product.description[:2400]))
    if product.is_sale and product.old_price and product.old_price > product.price:
        lines.append(f"\n<s>{product.old_price:.2f}</s> <b>{product.price:.2f} грн</b>")
    else:
        lines.append(f"\n<b>{product.price:.2f} грн</b>")
    lines.append("В наявності" if product.stock > 0 else "Немає в наявності")

    text = "\n".join(lines)
    markup = kb.product_card(product, in_cart)
    photo = product.photo_file_id or product.photo_url

    if photo:
        try:
            await callback.message.delete()
        except Exception:
            pass
        await callback.message.answer_photo(photo, caption=text if len(text) <= 1000 else "\n".join(lines[:2] + lines[-2:]), reply_markup=markup)
    else:
        try:
            await callback.message.edit_text(text, reply_markup=markup)
        except Exception:
            await callback.message.answer(text, reply_markup=markup)
    await callback.answer()
