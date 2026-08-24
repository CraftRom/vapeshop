"""Приймання апдейтів Telegram через вебхук.

Потрібно для serverless: у Vercel немає процесу, який міг би тримати
довгий polling. На власному сервері це теж робочий варіант — вмикається
через WEBHOOK_SECRET + PUBLIC_URL.
"""
from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import Update
from fastapi import APIRouter, HTTPException, Request, status

from bot.factory import bot_id, build_bot, build_dispatcher, webhook_path
from aiogram.types import MenuButtonWebApp, WebAppInfo

from shop.config import settings

router = APIRouter()
log = logging.getLogger("webhook")

# У довгоживучому процесі збираємо один раз; у serverless модуль і так
# створюється заново на кожен холодний старт.
_bot = None
_dp = None


_bot_token = None


def _instances():
    """Бот і диспетчер. Перебудовуються, якщо токен змінився.

    Без перевірки токена теплий інстанс продовжив би відповідати старим
    ботом ще довго після заміни BOT_TOKEN.
    """
    global _bot, _dp, _bot_token
    if _bot is None or _bot_token != settings.bot_token:
        _bot = build_bot()
        _dp = build_dispatcher()
        _bot_token = settings.bot_token
    return _bot, _dp


@router.post("/telegram/{secret}")
async def legacy_webhook(secret: str):
    """Стара адреса без ідентифікатора бота.

    Приймати сюди апдейти небезпечно: на цю ж адресу шле і попередній бот,
    якщо в нього лишився зареєстрований вебхук, а відповідали б ми поточним.
    Тому відхиляємо й підказуємо, що робити.
    """
    log.warning(
        "Апдейт на стару адресу вебхука. Виконайте /api/telegram-setup, "
        "а старому боту зробіть deleteWebhook."
    )
    raise HTTPException(status.HTTP_410_GONE, "Адресу вебхука змінено — перезапустіть setup")


@router.post("/telegram/{secret}/{hook_bot_id}")
async def telegram_webhook(secret: str, hook_bot_id: str, request: Request):
    if not settings.webhook_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Вебхук не налаштовано")
    if secret != settings.webhook_secret:
        # Не уточнюємо причину — стороннім знати нічого не треба
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")

    if hook_bot_id != bot_id():
        # Апдейт від бота, який у нас більше не налаштований
        log.warning(
            "Апдейт від бота %s, а налаштований %s. У старого бота лишився "
            "вебхук — зніміть його: /api/telegram-detach",
            hook_bot_id, bot_id(),
        )
        raise HTTPException(status.HTTP_409_CONFLICT, "Цей бот більше не обслуговується")

    bot, dp = _instances()
    try:
        update = Update.model_validate(await request.json(), context={"bot": bot})
        await dp.feed_update(bot, update)
    except Exception:
        # Помилку логуємо, але віддаємо 200: інакше Telegram нескінченно
        # ретраїтиме той самий апдейт і заблокує чергу.
        log.exception("Помилка обробки апдейта")

    return {"ok": True}


@router.get("/telegram-detach")
async def detach_old_bot(token: str = "", bot_token: str = ""):
    """Знімає вебхук зі старого бота.

    Потрібно після заміни BOT_TOKEN: у попереднього бота вебхук лишається
    зареєстрованим, і Telegram далі шле його апдейти нам. Ми їх відхиляємо,
    але користувач старого бота бачить мовчання замість пояснення, а в
    логах накопичується шум.

    Токен старого бота передається параметром і ніде не зберігається.
    """
    if not settings.cron_secret or token != settings.cron_secret:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if ":" not in bot_token:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Вкажіть bot_token старого бота")

    old = Bot(token=bot_token)
    try:
        me = await old.get_me()
        await old.delete_webhook(drop_pending_updates=True)
        return {"detached": me.username, "bot_id": me.id}
    except Exception as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Telegram відмовив: {exc}")
    finally:
        await old.session.close()


@router.get("/telegram-setup")
async def setup_webhook(token: str = ""):
    """Одноразова реєстрація вебхука в Telegram.

    Викликати після деплою: /api/telegram-setup?token=<CRON_SECRET>
    """
    # 404, а не 401: службовий маршрут не має підтверджувати своє існування
    # тому, хто не знає токена
    if not settings.cron_secret or token != settings.cron_secret:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if not settings.public_url or not settings.webhook_secret:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Задайте PUBLIC_URL і WEBHOOK_SECRET")

    bot, _ = _instances()
    url = settings.public_url.rstrip("/") + webhook_path()
    await bot.set_webhook(url, drop_pending_updates=True)

    # Синя кнопка біля поля вводу — головний вхід у вітрину.
    # Telegram вимагає https, тож на локальному хості вона не зʼявиться.
    shop_url = settings.public_url.rstrip("/") + "/app/"
    menu_set = False
    if shop_url.startswith("https://"):
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Магазин", web_app=WebAppInfo(url=shop_url))
        )
        menu_set = True

    me = await bot.get_me()
    info = await bot.get_webhook_info()
    return {
        "bot": f"@{me.username}",
        "bot_id": me.id,
        "webhook_url": url,
        "pending_updates": info.pending_update_count,
        "shop_url": shop_url,
        "menu_button": "встановлено" if menu_set else "пропущено: потрібен https",
    }
