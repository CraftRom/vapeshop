from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.auth import require_admin
from api.schemas import PromoIn, PromoOut
from shop.db import get_session
from shop.models import PromoCode, PromoUsage

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("", response_model=list[PromoOut])
async def list_promos(session: AsyncSession = Depends(get_session)):
    return list(await session.scalars(select(PromoCode).order_by(PromoCode.created_at.desc())))


@router.post("", response_model=PromoOut, status_code=201)
async def create_promo(data: PromoIn, session: AsyncSession = Depends(get_session)):
    code = data.code.strip().upper()
    exists = await session.scalar(select(PromoCode.id).where(func.upper(PromoCode.code) == code))
    if exists:
        raise HTTPException(409, "Промокод із таким кодом уже існує")
    promo = PromoCode(**data.model_dump() | {"code": code})
    session.add(promo)
    await session.commit()
    await session.refresh(promo)
    return promo


@router.put("/{promo_id}", response_model=PromoOut)
async def update_promo(promo_id: int, data: PromoIn, session: AsyncSession = Depends(get_session)):
    promo = await session.get(PromoCode, promo_id)
    if not promo:
        raise HTTPException(404, "Промокод не знайдено")
    for key, value in data.model_dump().items():
        setattr(promo, key, value.upper() if key == "code" else value)
    await session.commit()
    await session.refresh(promo)
    return promo


@router.delete("/{promo_id}", status_code=204)
async def delete_promo(promo_id: int, session: AsyncSession = Depends(get_session)):
    promo = await session.get(PromoCode, promo_id)
    if not promo:
        raise HTTPException(404, "Промокод не знайдено")
    promo.is_active = False
    await session.commit()


@router.get("/{promo_id}/usages")
async def promo_usages(promo_id: int, session: AsyncSession = Depends(get_session)):
    rows = await session.scalars(
        select(PromoUsage).where(PromoUsage.promo_id == promo_id).order_by(PromoUsage.created_at.desc())
    )
    return [{"user_id": u.user_id, "order_id": u.order_id, "created_at": u.created_at} for u in rows]
