"""Загальна підтримка клієнтів через Telegram-команду /ask.

На відміну від order_chat, ця стрічка не прив'язана до замовлення. Вона
потрібна для технічних проблем, загальних питань, помилок Mini App та
ситуацій, коли замовлення ще не створено.
"""
from __future__ import annotations

import logging
from html import escape

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

from shop.repo.base import Repository
from shop.services.status_messages import is_permanent_delivery_error

log = logging.getLogger(__name__)

MAX_LENGTH = 2000


def esc(value) -> str:
    return escape(str(value or ""), quote=False)


def support_keyboard() -> ReplyKeyboardMarkup:
    """У режимі /ask лишаємо тільки завершення звернення.

    Це reply-клавіатура, а не inline: вона замінює звичайне меню
    «Магазин / Довідка» на весь час діалогу й не дає випадково перейти
    в інший сценарій, поки повідомлення маршрутизуються в підтримку.
    """
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ Завершити звернення")]],
        resize_keyboard=True,
    )


async def is_active(repo: Repository, user_id: int) -> bool:
    thread = await repo.get_support_thread_for_user(user_id)
    return bool(thread and thread.status == "open")


async def start(repo: Repository, user_id: int) -> tuple[object, bool]:
    """Входить у режим /ask.

    Якщо сесія вже відкрита, продовжує саме її — повторна команда /ask не
    дробить одну розмову на кілька чатів. Якщо попередню сесію закрито,
    ensure_support_thread створює новий thread і ніколи не оживляє старий.
    """
    await repo.set_chat_order(user_id, None)
    current = await repo.get_support_thread_for_user(user_id)
    if current:
        return current, False
    return await repo.ensure_support_thread(user_id), True


async def close(
    repo: Repository,
    user_id: int,
    *,
    closed_by: str = "client",
    closed_by_name: str = "Клієнт",
    close_reason: str = "done",
):
    """Закриває лише поточну активну сесію клієнта.

    Повторний /done є безпечним no-op. Нова сесія тут не створюється.
    """
    thread = await repo.get_support_thread_for_user(user_id)
    if not thread:
        return None, False
    return await repo.close_support_thread(
        thread.id,
        closed_by=closed_by,
        closed_by_name=closed_by_name,
        close_reason=close_reason,
    )


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
    """Записує повідомлення лише в уже відкриту /ask-сесію.

    Важливо: цей метод принципово НЕ створює thread. Якщо менеджер закрив
    сесію між перевіркою хендлера та фактичним записом, повідомлення не
    повинно мовчки створити новий чат. Нову сесію створює тільки явний /ask.
    """
    thread = await repo.get_support_thread_for_user(user.id)
    if not thread:
        return None
    saved = await repo.add_support_message_if_open({
        "thread_id": thread.id,
        "user_id": user.id,
        "direction": "in",
        "author": user.first_name or user.username or f"id{user.tg_id}",
        "text": text,
        "tg_message_id": None,
        "is_read": False,
        **(attachment or {}),
    })

    if saved is None:
        return None

    from shop.services.panel_notifications import safe_publish
    author = user.first_name or user.username or f"id{user.tg_id}"
    await safe_publish(
        repo,
        "support.message",
        f"Нове повідомлення в підтримку · #{thread.id}",
        text,
        href=f"/support?thread={thread.id}",
        entity_id=thread.id,
        actor=author,
    )

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
        # Reply-клавіатуру тут не чіпаємо. Вона вже встановлена на вході
        # в /ask. Це прибирає гонку: якщо менеджер закрив чат одночасно з
        # відповіддю, пізніше доставлена відповідь не поверне кнопку
        # «Завершити звернення» поверх уже відновленого головного меню.
        sent = await bot.send_message(
            user.tg_id,
            "💬 <b>Відповідь менеджера</b>\n\n"
            f"{esc(text)}{signature}",
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


async def notify_closed_by_staff(bot, repo: Repository, thread, author: str, reply_markup=None) -> bool:
    """Сповіщає клієнта, що менеджер завершив саме цю сесію.

    Статус у БД уже закритий до виклику цієї функції. Невдала доставка не
    може відкотити закриття: це лише повідомлення користувачу.
    """
    user = thread.user or await repo.get_user(thread.user_id)
    if not user or user.bot_reachable is False:
        return False
    who = f" менеджером {esc(author)}" if author else " менеджером"
    try:
        await bot.send_message(
            user.tg_id,
            f"✅ <b>Звернення #{thread.id} завершено{who}</b>\n\n"
            "Історія цього звернення збережена. Якщо виникне нове питання — "
            "створіть нове звернення кнопкою «🆘 Підтримка» або командою /ask.",
            reply_markup=reply_markup,
        )

        # Закриття менеджером і новий /ask можуть прилетіти майже одночасно.
        # Якщо за час доставки клієнт уже створив НОВУ сесію, попереднє
        # повідомлення могло повернути головне меню поверх режиму /ask.
        # Перевіряємо стан після Telegram-відправки й виправляємо клавіатуру.
        active = await repo.get_support_thread_for_user(user.id)
        if active and active.id != thread.id:
            await bot.send_message(
                user.tg_id,
                f"🆘 Звернення #{active.id} активне. Продовжуйте писати сюди.",
                reply_markup=support_keyboard(),
            )
    except Exception as exc:
        if is_permanent_delivery_error(exc):
            await repo.set_bot_reachable(user.tg_id, False)
        log.warning(
            "Не вдалося повідомити клієнта про закриття підтримки %s",
            thread.id,
            extra={"event": "support.close_notify.failed", "threadId": thread.id},
            exc_info=True,
        )
        return False
    await repo.set_bot_reachable(user.tg_id, True)
    return True
