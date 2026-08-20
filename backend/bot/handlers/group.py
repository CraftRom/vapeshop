"""Реакція на додавання бота в групу чи канал.

Повідомлення в публічних чатах перехоплює PrivateOnlyMiddleware — до цього
роутера вони не доходять. Тут лишається тільки подія входу, яка приходить
іншим спостерігачем і мідлваром не зачіпається.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.enums import ChatMemberStatus, ChatType
from aiogram.types import ChatMemberUpdated

from bot.greeting import send_greeting
from shop.config import settings
from shop.services.shop_settings import current

router = Router(name="group")

PUBLIC_CHATS = {ChatType.GROUP, ChatType.SUPERGROUP, ChatType.CHANNEL}
JOINED = {ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR}


@router.my_chat_member(F.chat.type.in_(PUBLIC_CHATS))
async def added_to_chat(event: ChatMemberUpdated) -> None:
    was_in = event.old_chat_member.status in JOINED
    is_in = event.new_chat_member.status in JOINED
    if was_in or not is_in:
        return  # зміна прав, а не додавання
    if current().admin_chat_id and event.chat.id == current().admin_chat_id:
        return  # адмінський чат робочий, привітання там зайве
    await send_greeting(event)
