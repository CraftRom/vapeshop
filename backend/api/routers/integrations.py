"""Вхідні виклики зовнішніх систем.

Вебхук SalesDrive не має підпису — SalesDrive його не ставить. Захист
тримається на секретному токені в адресі (Установки → Webhook → URL):
32 випадкові байти, порівняння сталого часу, токен вирізається з журналу
запитів (shop/logging_setup.py). Невірний токен — 404, а не 403: адреса
для стороннього виглядає неіснуючою, і перебирати нема чого.

Відповідь завжди 200, коли запит прийнято: SalesDrive повторює вебхук на
помилку, а зміну, яку ми свідомо відхилили (недопустимий перехід статусу),
повторювати марно. Причину відмови видно в панелі біля замовлення.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from api.auth import Principal, require_sysadmin
from shop import security_log as security
from shop.repo.base import Repository
from shop.repo.factory import get_repo

log = logging.getLogger(__name__)

router = APIRouter()

MAX_BODY_BYTES = 256 * 1024


@router.post("/salesdrive/webhook/{token}", include_in_schema=False)
async def salesdrive_webhook(token: str, request: Request,
                             repo: Repository = Depends(get_repo)):
    from shop.services import salesdrive
    from shop.services.shop_settings import get_shop_settings

    shop = await get_shop_settings(repo)
    if not shop.salesdrive_enabled or not salesdrive.token_matches(shop, token):
        security.record("security.webhook.rejected", source="salesdrive",
                        reason="невірний токен або інтеграцію вимкнено")
        raise HTTPException(404, "Not Found")

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        raise HTTPException(413, "Завеликий запит")
    try:
        payload = await request.json()
    except ValueError as exc:
        raise HTTPException(400, "Очікується JSON") from exc
    if not isinstance(payload, dict):
        raise HTTPException(400, "Очікується JSON-обʼєкт")

    from api.routers.orders import _bot
    result = await salesdrive.handle_webhook(repo, payload, bot=_bot())
    log.info("Вебхук SalesDrive: %s", result.get("result"),
             extra={"event": "salesdrive.webhook", **{k: v for k, v in result.items()
                                                      if k in ("result", "orderId")}})
    return result


@router.post("/salesdrive/check")
async def salesdrive_check(_who: Principal = Depends(require_sysadmin),
                           repo: Repository = Depends(get_repo)):
    """Перевіряє лише мережу/субдомен/API-ключ. formId і мапінги не блокують тест."""
    return await _check(repo)


@router.get("/salesdrive/dictionaries")
async def salesdrive_dictionaries(_who: Principal = Depends(require_sysadmin),
                                  repo: Repository = Depends(get_repo)):
    """Актуальні статуси, оплати й доставки без ручного переписування з CRM.

    Ручне оновлення у налаштуваннях обходить кеш, щоб адміністратор одразу
    побачив щойно змінені довідники SalesDrive.
    """
    from shop.services import salesdrive
    from shop.services.shop_settings import get_shop_settings

    shop = await get_shop_settings(repo)
    if not (shop.salesdrive_domain or "").strip():
        raise HTTPException(400, "Не вказано субдомен SalesDrive")
    if not shop.salesdrive_api_connected:
        raise HTTPException(400, "Не задано API-ключ SalesDrive")
    try:
        return await salesdrive.dictionary_bundle(shop, force=True)
    except salesdrive.SalesDriveError as exc:
        raise HTTPException(502, str(exc)) from exc


async def _check(repo) -> dict:
    from shop.services import salesdrive
    from shop.services.shop_settings import get_shop_settings

    shop = await get_shop_settings(repo)
    if not (shop.salesdrive_domain or "").strip():
        return {"ok": False, "problem": "Не вказано субдомен SalesDrive"}
    if not shop.salesdrive_api_connected:
        return {"ok": False, "problem": "Не задано API-ключ SalesDrive"}
    try:
        await salesdrive.status_options(shop, force=True)
    except salesdrive.SalesDriveError as exc:
        return {"ok": False, "problem": str(exc)}
    form_id = salesdrive.telegram_form_id(shop)
    return {"ok": True, "problem": None, "telegramFormId": form_id or None,
            "sourceName": "ELFAR — Telegram Bot",
            "mappingReady": bool(mapping_ready(shop))}


def mapping_ready(shop) -> bool:
    from shop.services import salesdrive
    return bool(salesdrive.mapping(shop.salesdrive_status_map)
                and salesdrive.mapping(shop.salesdrive_payment_map)
                and salesdrive.mapping(shop.salesdrive_shipping_map))
