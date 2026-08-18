from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin
from api.schemas import CategoryIn, CategoryOut, ProductIn, ProductOut, StockIn
from shop.db import get_session
from shop.models import Category, Product

router = APIRouter(dependencies=[Depends(require_admin)])


# ----------------------------------------------------------------- категорії

@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(session: AsyncSession = Depends(get_session)):
    counts = (
        select(Product.category_id, func.count(Product.id).label("cnt"))
        .group_by(Product.category_id)
        .subquery()
    )
    rows = await session.execute(
        select(Category, func.coalesce(counts.c.cnt, 0))
        .outerjoin(counts, counts.c.category_id == Category.id)
        .order_by(Category.sort_order, Category.name)
    )
    return [
        CategoryOut(**CategoryOut.model_validate(c).model_dump() | {"products_count": cnt})
        for c, cnt in rows
    ]


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(data: CategoryIn, session: AsyncSession = Depends(get_session)):
    category = Category(**data.model_dump())
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return category


@router.put("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: int, data: CategoryIn, session: AsyncSession = Depends(get_session)
):
    category = await session.get(Category, category_id)
    if not category:
        raise HTTPException(404, "Категорію не знайдено")
    for key, value in data.model_dump().items():
        setattr(category, key, value)
    await session.commit()
    await session.refresh(category)
    return category


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(category_id: int, session: AsyncSession = Depends(get_session)):
    category = await session.get(Category, category_id)
    if not category:
        raise HTTPException(404, "Категорію не знайдено")
    count = await session.scalar(
        select(func.count(Product.id)).where(Product.category_id == category_id)
    )
    if count:
        raise HTTPException(409, f"У категорії {count} товарів. Спочатку перенесіть або видаліть їх.")
    await session.delete(category)
    await session.commit()


# -------------------------------------------------------------------- товари

@router.get("/products", response_model=list[ProductOut])
async def list_products(
    category_id: int | None = None,
    search: str | None = None,
    only_active: bool = False,
    session: AsyncSession = Depends(get_session),
):
    query = select(Product, Category.name).join(Category).order_by(Product.sort_order, Product.name)
    if category_id:
        query = query.where(Product.category_id == category_id)
    if search:
        query = query.where(Product.name.ilike(f"%{search}%"))
    if only_active:
        query = query.where(Product.is_active.is_(True))

    rows = await session.execute(query)
    return [
        ProductOut(**ProductOut.model_validate(p).model_dump() | {"category_name": cat_name})
        for p, cat_name in rows
    ]


@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(data: ProductIn, session: AsyncSession = Depends(get_session)):
    if not await session.get(Category, data.category_id):
        raise HTTPException(400, "Такої категорії немає")
    product = Product(**data.model_dump())
    session.add(product)
    await session.commit()
    await session.refresh(product)
    return product


@router.put("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int, data: ProductIn, session: AsyncSession = Depends(get_session)
):
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Товар не знайдено")
    for key, value in data.model_dump().items():
        setattr(product, key, value)
    await session.commit()
    await session.refresh(product)
    return product


@router.patch("/products/{product_id}/stock", response_model=ProductOut)
async def set_stock(product_id: int, data: StockIn, session: AsyncSession = Depends(get_session)):
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Товар не знайдено")
    product.stock = data.stock
    await session.commit()
    await session.refresh(product)
    return product


@router.delete("/products/{product_id}", status_code=204)
async def delete_product(product_id: int, session: AsyncSession = Depends(get_session)):
    product = await session.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Товар не знайдено")
    product.is_active = False  # м'яке видалення — історія замовлень залишається цілою
    await session.commit()
