from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_admin
from api.schemas import CategoryIn, CategoryOut, ProductIn, ProductOut, StockIn
from shop.repo.base import Repository
from shop.repo.factory import get_repo

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("/categories", response_model=list[CategoryOut])
async def list_categories(repo: Repository = Depends(get_repo)):
    return await repo.list_categories()


@router.post("/categories", response_model=CategoryOut, status_code=201)
async def create_category(data: CategoryIn, repo: Repository = Depends(get_repo)):
    return await repo.create_category(data.model_dump())


@router.put("/categories/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: int, data: CategoryIn, repo: Repository = Depends(get_repo)
):
    category = await repo.update_category(category_id, data.model_dump())
    if not category:
        raise HTTPException(404, "Категорію не знайдено")
    return category


@router.delete("/categories/{category_id}", status_code=204)
async def delete_category(category_id: int, repo: Repository = Depends(get_repo)):
    if not await repo.get_category(category_id):
        raise HTTPException(404, "Категорію не знайдено")
    if not await repo.delete_category(category_id):
        raise HTTPException(409, "У категорії є товари. Спочатку перенесіть або видаліть їх.")


@router.get("/products", response_model=list[ProductOut])
async def list_products(
    category_id: int | None = None,
    search: str | None = None,
    only_active: bool = False,
    repo: Repository = Depends(get_repo),
):
    return await repo.list_products(
        category_id=category_id, search=search, only_active=only_active
    )


@router.post("/products", response_model=ProductOut, status_code=201)
async def create_product(data: ProductIn, repo: Repository = Depends(get_repo)):
    if not await repo.get_category(data.category_id):
        raise HTTPException(400, "Такої категорії немає")
    return await repo.create_product(data.model_dump())


@router.put("/products/{product_id}", response_model=ProductOut)
async def update_product(
    product_id: int, data: ProductIn, repo: Repository = Depends(get_repo)
):
    product = await repo.update_product(product_id, data.model_dump())
    if not product:
        raise HTTPException(404, "Товар не знайдено")
    return product


@router.patch("/products/{product_id}/stock", response_model=ProductOut)
async def set_stock(product_id: int, data: StockIn, repo: Repository = Depends(get_repo)):
    product = await repo.set_stock(product_id, data.stock)
    if not product:
        raise HTTPException(404, "Товар не знайдено")
    return product


@router.delete("/products/{product_id}", status_code=204)
async def delete_product(product_id: int, repo: Repository = Depends(get_repo)):
    # М'яке видалення — історія замовлень має лишитись читабельною
    if not await repo.update_product(product_id, {"is_active": False}):
        raise HTTPException(404, "Товар не знайдено")
