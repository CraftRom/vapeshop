"""Налаштування магазину, які редагуються з панелі.

Значення перекривають змінні оточення: те, що не збережено тут, і далі
береться з .env. Тому свіжий деплой працює без жодного запису в базу.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from api.auth import require_admin
from api.schemas import ShopSettingsIn, ShopSettingsOut
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services.shop_settings import get_shop_settings, save_shop_settings

router = APIRouter(dependencies=[Depends(require_admin)])


@router.get("", response_model=ShopSettingsOut)
async def read_settings(repo: Repository = Depends(get_repo)):
    return await get_shop_settings(repo)


@router.put("", response_model=ShopSettingsOut)
async def write_settings(data: ShopSettingsIn, repo: Repository = Depends(get_repo)):
    # exclude_unset — часткове збереження не затирає полів, яких немає у запиті
    return await save_shop_settings(repo, data.model_dump(exclude_unset=True))
