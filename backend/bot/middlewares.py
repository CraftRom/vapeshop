from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot import keyboards as kb
from bot import texts
from shop.db import SessionMaker
from shop.services.users import get_or_create_user


class DatabaseMiddleware(BaseMiddleware):
    """Відкриває сесію та підтягує (або створює) користувача для кожного апдейту."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        async with SessionMaker() as session:
            data["session"] = session
            if tg_user and not tg_user.is_bot:
                user, is_new = await get_or_create_user(
                    session, tg_user.id, tg_user.username, tg_user.first_name
                )
                data["user"] = user
                data["is_new_user"] = is_new
            return await handler(event, data)


class AgeGateMiddleware(BaseMiddleware):
    """Нікотинові товари — 18+. Поки вік не підтверджено, доступний лише сам age gate."""

    ALLOWED_CALLBACKS = ("age:",)

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("user")
        if user is None or user.age_confirmed:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            if event.data and event.data.startswith(self.ALLOWED_CALLBACKS):
                return await handler(event, data)
            await event.answer("Спочатку підтвердьте вік", show_alert=True)
            return None

        if isinstance(event, Message):
            if event.text and event.text.startswith("/start"):
                return await handler(event, data)
            await event.answer(texts.AGE_GATE, reply_markup=kb.age_gate())
            return None

        return await handler(event, data)


class BlockedUserMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("user")
        if user is not None and user.is_blocked:
            if isinstance(event, CallbackQuery):
                await event.answer("Доступ обмежено", show_alert=True)
            return None
        return await handler(event, data)
