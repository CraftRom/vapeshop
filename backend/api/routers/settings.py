"""Налаштування магазину, які редагуються з панелі.

Значення перекривають змінні оточення: те, що не збережено тут, і далі
береться з .env. Тому свіжий деплой працює без жодного запису в базу.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from api.auth import Principal, require_admin, require_staff
from api.schemas import ShopSettingsIn, ShopSettingsOut
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services.shop_settings import current, get_shop_settings, save_shop_settings

router = APIRouter(dependencies=[Depends(require_staff)])

# Що оператор має право змінювати. Реферальні відсотки впливають на
# нарахування клієнтам, і це робоче питання; реквізити картки, адреса
# сайту й список менеджерів — ні, тож вони лишаються за адміністратором.
OPERATOR_FIELDS = {
    "referral_enabled", "referral_percent",
    "bonus_enabled", "bonus_max_percent",
    "volume_discount_enabled", "volume_discount_min", "volume_discount_percent",
}

# Параметри інфраструктури: розклад бекапів, ретенція, темп розсилки.
# Оператору вони не потрібні, а помилка в них дорога — окрема перевірка
# нижче тримає їх за адміністратором навіть якщо перелік вище розростеться.
# Розділи, закриті для всіх, крім системного адміністратора:
# Telegram-група, Бот і Mini App, Розсилки, Тихі години, Бекапи.
INFRA_FIELDS = {
    # Telegram-група
    "admin_chat_id", "admin_ids",
    # Бот і Mini App
    "bot_username", "miniapp_short_name", "public_url", "webhook_secret",
    # Розсилки
    "timezone", "broadcast_rate_per_second", "broadcast_chunk",
    # Тихі години
    "quiet_hours_enabled", "quiet_hours_start", "quiet_hours_end",
    # Бекапи
    "backup_enabled", "backup_hour", "backup_retention_days",
}


@router.get("", response_model=ShopSettingsOut)
async def read_settings(repo: Repository = Depends(get_repo)):
    return await get_shop_settings(repo)


@router.get("/environment")
async def environment(who: Principal = Depends(require_admin)):
    """Стан змінних оточення: задані чи ні. Значень не розкриваємо.

    Лише для адміністратора: перелік того, що налаштовано на сервері, —
    підказка для того, хто шукає діру в захисті.
    """
    from shop.config import settings as env

    # Передаємо чинні налаштування: адреса сайту й імʼя бота можуть бути
    # задані в панелі, а не в оточенні
    return {"items": env.environment_report(current())}


@router.put("", response_model=ShopSettingsOut)
async def write_settings(
    data: ShopSettingsIn,
    who: Principal = Depends(require_staff),
    repo: Repository = Depends(get_repo),
):
    # exclude_unset — часткове збереження не затирає полів, яких немає у запиті
    payload = data.model_dump(exclude_unset=True)

    # Інфраструктура — лише системному адміністраторові. Ні адміністратор
    # магазину, ні менеджер сюди не дістають: помилка в токені бота чи в
    # розкладі бекапів кладе не свій відділ роботи, а весь магазин.
    if not who.is_sysadmin:
        infra = sorted(set(payload) & INFRA_FIELDS)
        if infra:
            raise HTTPException(
                403,
                "Ці налаштування змінює лише системний адміністратор: "
                + ", ".join(infra),
            )

    if not who.is_admin:
        forbidden = sorted(set(payload) - (OPERATOR_FIELDS - INFRA_FIELDS))
        if forbidden:
            raise HTTPException(
                403,
                "Оператор може змінювати лише реферальну програму. "
                f"Поза доступом: {', '.join(forbidden)}",
            )

    return await save_shop_settings(repo, payload)
