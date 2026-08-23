"""Відповіді клієнта операторові.

Реєструється ОСТАННІМ: спрацьовує лише на те, що не розібрали інші
роутери. Інакше він перехоплював би кнопки меню й кроки оформлення.
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from shop.entities import User
from shop.repo.base import Repository
from shop.services import order_chat as chat

router = Router(name="chat")

# Найдовше повідомлення, яке приймаємо в стрічку. Довші майже завжди —
# випадково вставлений текст, а не звернення до оператора.
MAX_LENGTH = 2000


async def _deliver(repo: Repository, user: User, text: str, order_id: int, bot=None) -> str:
    order = await repo.get_order(order_id)
    if not order or order.user_id != user.id:
        return "Це замовлення не знайдено."
    await chat.save_incoming(repo, order, user, text, bot=bot)
    return f"Передали оператору щодо замовлення №{order.id}. Відповідь надійде сюди."


@router.message(F.text & ~F.text.startswith("/"))
async def incoming(
    message: Message, repo: Repository, user: User, state: FSMContext
) -> None:
    # Під час оформлення замовлення текст належить крокам FSM, не чату
    if await state.get_state() is not None:
        return

    text = (message.text or "").strip()
    if not text:
        return
    if len(text) > MAX_LENGTH:
        await message.answer(
            f"Повідомлення задовге — до {MAX_LENGTH} символів. "
            "Опишіть коротко, оператор перепитає."
        )
        return

    order_id = await chat.route_incoming(repo, user, message)
    if order_id:
        await message.answer(await _deliver(repo, user, text, order_id, message.bot))
        return

    open_orders = await chat.open_orders_for(repo, user.id)
    if not open_orders:
        await message.answer(
            "Щоб написати оператору, потрібне активне замовлення. "
            "Оформіть його в магазині — і зможете спитати тут."
        )
        return

    # Кілька відкритих замовлень: просимо вибрати, до якого питання
    await state.update_data(pending_message=text)
    await message.answer(
        "У вас кілька активних замовлень. До якого стосується повідомлення?",
        reply_markup=chat.pick_order_keyboard(open_orders),
    )


@router.callback_query(F.data.startswith("chat:"))
async def pick_order(
    callback: CallbackQuery, repo: Repository, user: User, state: FSMContext
) -> None:
    try:
        order_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Кнопка застаріла", show_alert=True)
        return

    data = await state.get_data()
    text = (data.get("pending_message") or "").strip()
    if not text:
        await callback.answer("Повідомлення вже не збереглося — напишіть ще раз", show_alert=True)
        return

    result = await _deliver(repo, user, text, order_id, callback.bot)
    await state.update_data(pending_message=None)
    await callback.message.edit_text(result)
    await callback.answer()
