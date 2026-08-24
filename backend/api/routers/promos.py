from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth import require_staff
from api.schemas import PromoIn, PromoOut
from shop.repo.base import Repository
from shop.repo.factory import get_repo

router = APIRouter(dependencies=[Depends(require_staff)])


@router.get("", response_model=list[PromoOut])
async def list_promos(repo: Repository = Depends(get_repo)):
    return await repo.list_promos()


@router.post("", response_model=PromoOut, status_code=201)
async def create_promo(data: PromoIn, repo: Repository = Depends(get_repo)):
    if await repo.get_promo_by_code(data.code):
        raise HTTPException(409, "Промокод із таким кодом уже існує")
    return await repo.create_promo(data.model_dump())


@router.get("/{promo_id}", response_model=PromoOut)
async def get_promo(promo_id: int, repo: Repository = Depends(get_repo)):
    found = await repo.get_promo(promo_id)
    if not found:
        raise HTTPException(404, "Промокод не знайдено")
    return found


@router.put("/{promo_id}", response_model=PromoOut)
async def update_promo(promo_id: int, data: PromoIn, repo: Repository = Depends(get_repo)):
    promo = await repo.update_promo(promo_id, data.model_dump())
    if not promo:
        raise HTTPException(404, "Промокод не знайдено")
    return promo


@router.delete("/{promo_id}", status_code=204)
async def delete_promo(promo_id: int, repo: Repository = Depends(get_repo)):
    """М'яке приховування: код перестає діяти, статистика застосувань лишається."""
    if not await repo.update_promo(promo_id, {"is_active": False}):
        raise HTTPException(404, "Промокод не знайдено")


@router.delete("/{promo_id}/purge", status_code=204)
async def purge_promo(promo_id: int, repo: Repository = Depends(get_repo)):
    """Остаточне видалення разом з історією застосувань."""
    if not await repo.purge_promo(promo_id):
        raise HTTPException(404, "Промокод не знайдено")
