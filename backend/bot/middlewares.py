from __future__ import annotations

import logging

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

from bot import keyboards as kb
from bot import texts
from bot import faq
from bot.greeting import is_command_trigger, send_greeting
from shop.config import settings
from shop.services.shop_settings import current, get_shop_settings
from shop.repo.factory import open_repo
from shop.services.shop_service import get_or_create_user


log = logging.getLogger(__name__)


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


class PrivateOnlyMiddleware(BaseMiddleware):
    """Бот працює лише в особистому листуванні.

    У групі чи каналі відповідь бачать усі присутні, а хендлери віддають
    приватні дані: профіль показує бонусний рахунок і суму витрат, кошик —
    що саме людина набрала, історія — її замовлення з адресою. Тому все,
    що не приватний чат, обривається тут, до роутерів.

    Виняток один — адмінський чат із settings.admin_chat_id: там менеджери
    натискають кнопки статусу замовлень і викликають /stats. Це і є його
    призначення. Особисті ідентифікатори адміністраторів сюди не додаємо:
    інакше адміністратор, покликавши /stats у сторонній групі, вивалив би
    туди виручку магазину.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        chat = data.get("event_chat")
        if chat is None or chat.type == "private":
            return await handler(event, data)

        # current() — синхронний знімок кешу: репозиторій тут ще не відкрито
        admin_chat_id = current().admin_chat_id
        if admin_chat_id and chat.id == admin_chat_id:
            return await handler(event, data)

        # Натискання кнопки в групі: коротка підказка тому, хто натиснув,
        # без повідомлення в сам чат
        if isinstance(event, CallbackQuery):
            await event.answer(
                "Магазин працює лише в особистому чаті з ботом", show_alert=True
            )
            return None

        # Привітання шлемо лише коли бота явно покликали: командою /start
        # або згадкою. На решту реплік у чаті бот мовчить, інакше він
        # засмічував би розмову відповіддю на кожне повідомлення.
        if not isinstance(event, Message):
            return None

        text = event.text or event.caption or ""

        # Команда — це прохання показати магазин, відповідаємо привітанням
        if is_command_trigger(text):
            await send_greeting(event)
            return None

        # Згадка: спершу пробуємо відповісти по суті й лише потім вітаємось.
        # Інакше на «@бот яка доставка» людина отримала б загальне «ласкаво
        # просимо» — формально відповідь, а насправді ні.
        #
        # Відповідаємо лише загальними правилами: персональне (статус
        # замовлення, бонуси, реферальне посилання) у публічний чат не йде
        # взагалі, бо його побачили б усі присутні.
        if _mentions_bot(event):
            rule = faq.match(text, current(), public=True)
            if rule:
                await _reply_public(event, rule)
            else:
                await send_greeting(event)

        return None


def _mentions_bot(event) -> bool:
    """Чи покликали саме нашого бота."""
    username = (current().bot_username or "").lstrip("@").lower()
    text = (event.text or event.caption or "").lower()
    return bool(username) and f"@{username}" in text


async def _reply_public(event, rule) -> None:
    """Відповідь у групу: загальний текст плюс кнопка в особистий чат."""
    from bot import keyboards as kb

    try:
        await event.answer(
            faq.render(rule, current()) +
            "\n\n<i>Замовлення й особисті питання — в особистому чаті.</i>",
            reply_markup=kb.to_private_chat(),
        )
    except Exception:
        # У каналі бот може не мати права писати — це не збій застосунку
        log.info("Не вдалося відповісти в публічному чаті", exc_info=True)


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
        if tg_user and tg_user.id in current().admin_id_list:
            return await handler(event, data)

        if isinstance(event, CallbackQuery):
            if event.data and event.data.startswith(self.ALLOWED_CALLBACKS):
                return await handler(event, data)
            await event.answer("Спочатку підтвердьте вік", show_alert=True)
            return None

        if isinstance(event, Message):
            if event.text and event.text.startswith("/start"):
                return await handler(event, data)
            repo = data.get("repo")
            shop = await get_shop_settings(repo) if repo else None
            min_age = shop.min_age if shop else None
            await event.answer(texts.age_gate(min_age), reply_markup=kb.age_gate())
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
