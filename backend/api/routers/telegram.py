"""Приймання апдейтів Telegram через вебхук.

Потрібно для serverless: у Vercel немає процесу, який міг би тримати
довгий polling. На власному сервері це теж робочий варіант — вмикається
через WEBHOOK_SECRET + PUBLIC_URL.
"""
from __future__ import annotations

import logging

from aiogram.types import Update
from fastapi import APIRouter, HTTPException, Request, status

from bot.factory import build_bot, build_dispatcher, webhook_path
from shop.config import settings

router = APIRouter()
log = logging.getLogger("webhook")

# У довгоживучому процесі збираємо один раз; у serverless модуль і так
# створюється заново на кожен холодний старт.
_bot = None
_dp = None


def _instances():
    global _bot, _dp
    if _bot is None:
        _bot = build_bot()
        _dp = build_dispatcher()
    return _bot, _dp


@router.post("/telegram/{secret}")
async def telegram_webhook(secret: str, request: Request):
    if not settings.webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Вебхук не налаштовано")
    if secret != settings.webhook_secret:
        # Не уточнюємо причину — стороннім знати нічого не треба
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    bot, dp = _instances()
    try:
        update = Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception:
        # Помилку логуємо, але віддаємо 200: інакше Telegram нескінченно
        # ретраїтиме той самий апдейт і заблокує чергу.
        log.exception("Помилка обробки апдейта")

    return {"ok": True}


@router.get("/telegram-setup")
async def setup_webhook(token: str = ""):
    """Одноразова реєстрація вебхука в Telegram.

    Викликати після деплою: /api/telegram-setup?token=<CRON_SECRET>
    """
    if not settings.cron_secret or token != settings.cron_secret:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невірний токен")
    if not settings.public_url or not settings.webhook_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Задайте PUBLIC_URL і WEBHOOK_SECRET")

    bot, _ = _instances()
    url = settings.public_url.rstrip("/") + webhook_path()
    await bot.set_webhook(url, drop_pending_updates=True)
    info = await bot.get_webhook_info()
    return {"webhook_url": url, "pending_updates": info.pending_update_count}
