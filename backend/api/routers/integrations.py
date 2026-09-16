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
    """Перевірка звʼязку для панелі (лише системний адміністратор).

    Читає одну заявку через API списку: так перевіряється і домен, і
    API-ключ, і нічого не створюється в CRM. Ключ форми цим не
    перевіряється — API додавання заявок не має способу «сухого» виклику.
    """
    return await _check(repo)


async def _check(repo) -> dict:
    import httpx

    from shop.services import salesdrive
    from shop.services.shop_settings import get_shop_settings

    shop = await get_shop_settings(repo)
    if salesdrive.telegram_form_id(shop) <= 0:
        return {"ok": False, "problem": "Не вказано ID форми SalesDrive «ELFAR — Telegram Bot». Вкажіть formId у налаштуваннях інтеграції"}
    if not (shop.salesdrive_domain or "").strip():
        return {"ok": False, "problem": "Не вказано субдомен SalesDrive"}
    if not shop.salesdrive_api_connected:
        return {"ok": False, "problem": "Не задано API-ключ (потрібен для перевірки й читання заявок)"}
    try:
        async with httpx.AsyncClient(timeout=salesdrive.REQUEST_TIMEOUT) as client:
            response = await client.get(
                salesdrive.base_url(shop) + "/api/order/list/",
                params={"page": 1, "limit": 1},
                headers={"Form-Api-Key": shop.salesdrive_api_key, "Accept": "application/json"},
            )
    except httpx.HTTPError as exc:
        return {"ok": False, "problem": f"SalesDrive недоступний: {type(exc).__name__}"}
    if response.status_code in (401, 403):
        return {"ok": False, "problem": "SalesDrive відхилив API-ключ"}
    if response.status_code == 429:
        return {"ok": False, "problem": "Ліміт API списку заявок: 10 запитів на хвилину. Спробуйте за хвилину"}
    if response.status_code >= 400:
        return {"ok": False, "problem": f"SalesDrive відповів {response.status_code}"}
    return {"ok": True, "problem": None,
            "telegramFormId": salesdrive.telegram_form_id(shop),
            "sourceName": "ELFAR — Telegram Bot"}
