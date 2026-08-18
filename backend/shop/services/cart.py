from __future__ import annotations

from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shop.models import CartItem, Product


async def get_items(session: AsyncSession, user_id: int) -> list[CartItem]:
    result = await session.scalars(
        select(CartItem)
        .where(CartItem.user_id == user_id)
        .options(selectinload(CartItem.product))
        .order_by(CartItem.id)
    )
    return list(result)


async def add(session: AsyncSession, user_id: int, product_id: int, qty: int = 1) -> CartItem | None:
    product = await session.get(Product, product_id)
    if not product or not product.is_active:
        return None

    item = await session.scalar(
        select(CartItem).where(CartItem.user_id == user_id, CartItem.product_id == product_id)
    )
    new_qty = (item.qty if item else 0) + qty
    if new_qty > product.stock:
        new_qty = product.stock
    if new_qty <= 0:
        if item:
            await session.delete(item)
            await session.commit()
        return None

    if item:
        item.qty = new_qty
    else:
        item = CartItem(user_id=user_id, product_id=product_id, qty=new_qty)
        session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


async def set_qty(session: AsyncSession, user_id: int, product_id: int, qty: int) -> CartItem | None:
    item = await session.scalar(
        select(CartItem).where(CartItem.user_id == user_id, CartItem.product_id == product_id)
    )
    if not item:
        return None
    if qty <= 0:
        await session.delete(item)
        await session.commit()
        return None
    product = await session.get(Product, product_id)
    item.qty = min(qty, product.stock if product else qty)
    await session.commit()
    return item


async def clear(session: AsyncSession, user_id: int) -> None:
    await session.execute(delete(CartItem).where(CartItem.user_id == user_id))
    await session.commit()


async def subtotal(session: AsyncSession, user_id: int) -> Decimal:
    items = await get_items(session, user_id)
    return sum((i.product.price * i.qty for i in items), Decimal(0))


async def validate_stock(session: AsyncSession, user_id: int) -> list[str]:
    """Повертає список проблем: товар зник або залишку не вистачає."""
    problems = []
    for item in await get_items(session, user_id):
        p = item.product
        if not p or not p.is_active:
            problems.append(f"«{p.name if p else 'товар'}» більше недоступний")
        elif p.stock < item.qty:
            problems.append(f"«{p.name}»: в наявності {p.stock} шт, у кошику {item.qty}")
    return problems
