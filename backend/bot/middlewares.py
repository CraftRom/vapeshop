from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot import keyboards as kb
from bot import texts
from shop.config import settings
from shop.repo.factory import open_repo
from shop.services.shop_service import get_or_create_user


class RepositoryMiddleware(BaseMiddleware):
    """Відкриває репозиторій і підтягує користувача на кожен апдейт.

    Хендлери отримують `repo` і не знають, Postgres це чи Firestore.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        tg_user = data.get("event_from_user")
        async with open_repo() as repo:
            data["repo"] = repo
            if tg_user and not tg_user.is_bot:
                user, is_new = await get_or_create_user(
                    repo, tg_user.id, tg_user.username, tg_user.first_name
                )
                data["user"] = user
                data["is_new_user"] = is_new
            return await handler(event, data)


class AgeGateMiddleware(BaseMiddleware):
    """Нікотинові товари — 18+. Поки вік не підтверджено, доступний лише age gate.

    Персонал пропускаємо: адміністратор керує замовленнями, а не купує. Інакше
    менеджер, який не заходив у бот як покупець, не міг би ні натиснути кнопку
    статусу в адмін-чаті, ні викликати /stats — а сама група отримувала б
    повідомлення про підтвердження віку.
    """

    ALLOWED_CALLBACKS = ("age:",)

    async def __call__(self, handler, event: TelegramObject, data: dict[str, Any]) -> Any:
        user = data.get("user")
        if user is None or user.age_confirmed:
            return await handler(event, data)

        tg_user = data.get("event_from_user")
        if tg_user and tg_user.id in settings.admin_id_list:
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
