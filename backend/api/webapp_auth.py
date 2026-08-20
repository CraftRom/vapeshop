"""Автентифікація Telegram Mini App.

Telegram передає у вікно Mini App рядок initData, підписаний ключем бота.
Перевірка підпису — єдине, що відрізняє справжнього покупця від будь-кого,
хто відкрив API у браузері. Без неї можна було б оформити замовлення від
чужого імені, підставивши довільний tg_id.

Алгоритм описаний у документації Telegram:
  secret_key   = HMAC_SHA256(key="WebAppData", msg=<bot_token>)
  data_check   = рядки "ключ=значення", відсортовані за ключем, через \\n
  очікуваний   = HMAC_SHA256(key=secret_key, msg=data_check).hexdigest()
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

from fastapi import Depends, Header, HTTPException

from shop.config import settings
from shop.entities import User
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services.shop_service import get_or_create_user

# Скільки максимум живе підпис. Telegram не оновлює initData під час сесії,
# тож надто короткий строк вибиватиме покупця посеред оформлення.
MAX_AGE_SECONDS = 24 * 60 * 60


class InitDataError(Exception):
    pass


def parse_init_data(init_data: str, bot_token: str, max_age: int = MAX_AGE_SECONDS) -> dict:
    """Перевіряє підпис і повертає розібрані поля. Кидає InitDataError."""
    if not init_data:
        raise InitDataError("Порожній initData")
    if not bot_token:
        raise InitDataError("Не заданий BOT_TOKEN")

    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received = pairs.pop("hash", None)
    if not received:
        raise InitDataError("У initData немає підпису")

    check_string = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    # compare_digest — щоб не зливати підпис через час порівняння
    if not hmac.compare_digest(expected, received):
        raise InitDataError("Підпис не збігається")

    auth_date = pairs.get("auth_date")
    if auth_date and max_age:
        try:
            age = time.time() - int(auth_date)
        except ValueError:
            raise InitDataError("Зіпсований auth_date")
        if age > max_age:
            raise InitDataError("Сесію прострочено, перезапустіть застосунок")

    if "user" in pairs:
        try:
            pairs["user"] = json.loads(pairs["user"])
        except json.JSONDecodeError:
            raise InitDataError("Зіпсовані дані користувача")

    return pairs


async def require_webapp_user(
    x_telegram_init_data: str = Header(default=""),
    repo: Repository = Depends(get_repo),
) -> User:
    """Покупець, який відкрив Mini App. Створюється при першому заході."""
    try:
        data = parse_init_data(x_telegram_init_data, settings.bot_token)
    except InitDataError as exc:
        raise HTTPException(401, str(exc))

    tg_user = data.get("user") or {}
    tg_id = tg_user.get("id")
    if not tg_id:
        raise HTTPException(401, "У initData немає користувача")

    user, _ = await get_or_create_user(
        repo,
        tg_id=int(tg_id),
        username=tg_user.get("username"),
        first_name=tg_user.get("first_name"),
        # start_param несе реферальний код із посилання t.me/bot?startapp=<code>
        referral_code=data.get("start_param"),
    )
    if user.is_blocked:
        raise HTTPException(403, "Доступ обмежено")
    return user
