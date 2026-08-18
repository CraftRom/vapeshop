from __future__ import annotations

import math

from aiogram import F, Router
from aiogram.types import CallbackQuery, InputMediaPhoto, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bot import keyboards as kb
from shop.models import CartItem, Category, Product, User

router = Router()
PAGE_SIZE = 8


async def _send_categories(target: Message | CallbackQuery, session: AsyncSession) -> None:
    items = list(
        await session.scalars(
            select(Category).where(Category.is_active.is_(True)).order_by(Category.sort_order, Category.name)
        )
    )
    if not items:
        text = "Каталог наповнюється. Зазирніть трохи пізніше."
        markup = None
    else:
        text = "<b>Каталог</b>\n\nОберіть категорію:"
        markup = kb.categories(items)

    if isinstance(target, CallbackQuery):
        try:
            await target.message.edit_text(text, reply_markup=markup)
        except Exception:
            await target.message.answer(text, reply_markup=markup)
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup)


@router.message(F.text == "🛍 Каталог")
async def catalog_message(message: Message, session: AsyncSession) -> None:
    await _send_categories(message, session)


@router.callback_query(F.data == "catalog")
async def catalog_callback(callback: CallbackQuery, session: AsyncSession) -> None:
    await _send_categories(callback, session)


async def _render_products(callback: CallbackQuery, session: AsyncSession, cat_id: int, page: int) -> None:
    category = await session.get(Category, cat_id)
    if not category:
        await callback.answer("Категорію не знайдено", show_alert=True)
        return

    total = await session.scalar(
        select(func.count(Product.id)).where(Product.category_id == cat_id, Product.is_active.is_(True))
    ) or 0
    pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(0, min(page, pages - 1))

    items = list(
        await session.scalars(
            select(Product)
            .where(Product.category_id == cat_id, Product.is_active.is_(True))
            .order_by(Product.sort_order, Product.name)
            .offset(page * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
    )

    header = f"<b>{category.name}</b>"
    if category.description:
        header += f"\n{category.description}"
    if not items:
        header += "\n\nУ цій категорії поки порожньо."

    try:
        await callback.message.edit_text(header, reply_markup=kb.products(items, cat_id, page, pages))
    except Exception:
        await callback.message.answer(header, reply_markup=kb.products(items, cat_id, page, pages))
    await callback.answer()


@router.callback_query(F.data.startswith("cat:"))
async def open_category(callback: CallbackQuery, session: AsyncSession) -> None:
    cat_id = int(callback.data.split(":")[1])
    await _render_products(callback, session, cat_id, 0)


@router.callback_query(F.data.startswith("catpage:"))
async def page_category(callback: CallbackQuery, session: AsyncSession) -> None:
    _, cat_id, page = callback.data.split(":")
    await _render_products(callback, session, int(cat_id), int(page))


@router.callback_query(F.data.startswith("prod:"))
async def open_product(callback: CallbackQuery, session: AsyncSession, user: User) -> None:
    product_id = int(callback.data.split(":")[1])
    product = await session.get(Product, product_id)
    if not product or not product.is_active:
        await callback.answer("Товар більше недоступний", show_alert=True)
        return

    in_cart = await session.scalar(
        select(CartItem.qty).where(CartItem.user_id == user.id, CartItem.product_id == product_id)
    ) or 0

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
