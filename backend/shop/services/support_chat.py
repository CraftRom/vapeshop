"""Загальна підтримка клієнтів через Telegram-команду /ask.

На відміну від order_chat, ця стрічка не прив'язана до замовлення. Вона
потрібна для технічних проблем, загальних питань, помилок Mini App та
ситуацій, коли замовлення ще не створено.
"""
from __future__ import annotations

import logging
from html import escape

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from shop.repo.base import Repository
from shop.services.status_messages import is_permanent_delivery_error

log = logging.getLogger(__name__)

MAX_LENGTH = 2000


def esc(value) -> str:
    return escape(str(value or ""), quote=False)


def support_keyboard() -> InlineKeyboardMarkup:
    """Швидке завершення режиму підтримки прямо в боті."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Завершити звернення", callback_data="support:done")
    ]])


async def is_active(repo: Repository, user_id: int) -> bool:
    thread = await repo.get_support_thread_for_user(user_id)
    return bool(thread and thread.status == "open")


async def start(repo: Repository, user_id: int):
    # Загальна підтримка — окремий контекст. Інакше після /done старий
    # chat_order_id залишався активним і наступне звичайне повідомлення могло
    # непомітно піти в чат минулого замовлення.
    await repo.set_chat_order(user_id, None)
    return await repo.ensure_support_thread(user_id)


async def close(repo: Repository, user_id: int):
    thread = await repo.get_support_thread_for_user(user_id)
    if not thread or thread.status != "open":
        return None
    return await repo.set_support_thread_status(thread.id, "closed")


def describe_attachment(message) -> dict | None:
    if getattr(message, "photo", None):
        return {
            "file_id": message.photo[-1].file_id,
            "file_kind": "photo",
            "file_name": "Фото",
        }
    if getattr(message, "document", None):
        return {
            "file_id": message.document.file_id,
            "file_kind": "document",
            "file_name": message.document.file_name or "Документ",
        }
    if getattr(message, "video", None):
        return {
            "file_id": message.video.file_id,
            "file_kind": "video",
            "file_name": "Відео",
        }
    if getattr(message, "voice", None):
        return {
            "file_id": message.voice.file_id,
            "file_kind": "voice",
            "file_name": "Голосове",
        }
    return None


async def save_incoming(
    repo: Repository,
    user,
    text: str,
    bot=None,
    attachment: dict | None = None,
):
    """Записує повідомлення клієнта й повертає актуальну стрічку."""
    thread = await repo.ensure_support_thread(user.id)
    saved = await repo.add_support_message({
        "thread_id": thread.id,
        "user_id": user.id,
        "direction": "in",
        "author": user.first_name or user.username or f"id{user.tg_id}",
        "text": text,
        "tg_message_id": None,
        "is_read": False,
        **(attachment or {}),
    })

    if bot is not None:
        await _notify_staff(bot, repo, thread.id, user, text)
    return saved


async def _notify_staff(bot, repo: Repository, thread_id: int, user, text: str) -> None:
    from shop.services.notifications import topic_kwargs
    from shop.services.shop_settings import get_shop_settings

    shop = await get_shop_settings(repo)
    if not shop.admin_chat_id:
        return

    who = f"@{esc(user.username)}" if user.username else esc(user.first_name or "клієнт")
    try:
        await bot.send_message(
            shop.admin_chat_id,
            "🆘 <b>Нове звернення в підтримку</b>\n"
            f"Від: {who}\n\n{esc(text)}\n\n"
            f"<i>Відповісти: панель → Підтримка → чат #{thread_id}</i>",
            **topic_kwargs(shop.chat_topic_id or shop.admin_topic_id),
        )
    except Exception:
        # Сповіщення в робочий чат — додаткове. Саме звернення вже лежить у БД
        # і не повинно губитися через проблеми Telegram із групою менеджерів.
        log.info("Не вдалося сповістити команду про звернення підтримки", exc_info=True)


async def send_to_client(
    bot,
    repo: Repository,
    thread,
    text: str,
    author: str = "",
) -> tuple[bool, object | None]:
    """Надсилає відповідь менеджера в приватний Telegram клієнта."""
    user = thread.user or await repo.get_user(thread.user_id)
    if not user:
        return False, None
    if user.bot_reachable is False:
        return False, None

    signature = f"\n\n<i>{esc(author)}</i>" if author else ""
    try:
        sent = await bot.send_message(
            user.tg_id,
            "💬 <b>Відповідь менеджера</b>\n\n"
            f"{esc(text)}{signature}",
            reply_markup=support_keyboard(),
        )
    except Exception as exc:
        if is_permanent_delivery_error(exc):
            await repo.set_bot_reachable(user.tg_id, False)
        log.warning(
            "Не вдалося доставити відповідь підтримки клієнту %s",
            user.tg_id,
            extra={
                "event": "support.delivery.failed",
                "threadId": thread.id,
                "clientId": user.tg_id,
                "permanent": is_permanent_delivery_error(exc),
            },
            exc_info=True,
        )
        return False, None

    await repo.set_bot_reachable(user.tg_id, True)
    return True, sent
