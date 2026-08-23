"""Налаштування магазину, які редагуються з панелі.

Значення перекривають змінні оточення: те, що не збережено тут, і далі
береться з .env. Тому свіжий деплой працює без жодного запису в базу.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth import Principal, require_staff
from api.schemas import ShopSettingsIn, ShopSettingsOut
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services.shop_settings import get_shop_settings, save_shop_settings

router = APIRouter(dependencies=[Depends(require_staff)])

# Що оператор має право змінювати. Реферальні відсотки впливають на
# нарахування клієнтам, і це робоче питання; реквізити картки, адреса
# сайту й список менеджерів — ні, тож вони лишаються за адміністратором.
OPERATOR_FIELDS = {
    "referral_enabled", "referral_percent",
    "bonus_enabled", "bonus_max_percent",
    "volume_discount_enabled", "volume_discount_min", "volume_discount_percent",
}


@router.get("", response_model=ShopSettingsOut)
async def read_settings(repo: Repository = Depends(get_repo)):
    return await get_shop_settings(repo)


@router.put("", response_model=ShopSettingsOut)
async def write_settings(
    data: ShopSettingsIn,
    who: Principal = Depends(require_staff),
    repo: Repository = Depends(get_repo),
):
    # exclude_unset — часткове збереження не затирає полів, яких немає у запиті
    payload = data.model_dump(exclude_unset=True)

    if not who.is_admin:
        forbidden = sorted(set(payload) - OPERATOR_FIELDS)
        if forbidden:
            raise HTTPException(
                403,
                "Оператор може змінювати лише реферальну програму. "
                f"Поза доступом: {', '.join(forbidden)}",
            )

    return await save_shop_settings(repo, payload)
