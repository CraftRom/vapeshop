"""Спілкування клієнта з менеджером.

Реєструється ОСТАННІМ: ловить лише те, що не розібрали інші роутери.

У клієнта може бути кілька активних замовлень, і різні менеджери ведуть
різні. Тому є явне перемикання: /orders показує список, вибір запам'ятовується
в базі (не у FSM — стан не переживає холодний старт у serverless).
"""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from shop.entities import STATUS_LABELS, User
from shop.repo.base import Repository
from bot import faq
from bot import keyboards as kb
from shop.services import order_chat as chat
from shop.services.shop_settings import get_shop_settings

router = Router(name="chat")

MAX_LENGTH = 2000


def _hint(order_id: int) -> str:
    return (
        f"Ви пишете щодо замовлення <b>№{order_id}</b>.\n"
        "Щоб перемкнутися на інше — /orders"
    )


@router.message(Command("orders", "zamovlennya"))
async def switch_order(message: Message, repo: Repository, user: User) -> None:
    """Список активних замовлень із вибором того, про яке говоримо."""
    open_orders = await chat.open_orders_for(repo, user.id)
    if not open_orders:
        await message.answer("Активних замовлень немає. Оформіть нове в магазині.")
        return

    lines = ["<b>Ваші активні замовлення</b>\n"]
    for o in open_orders:
        mark = " ← обрано" if o.id == user.chat_order_id else ""
        operator = f" · {o.operator_name}" if o.operator_name else ""
        lines.append(
            f"№{o.id} — {o.total:.0f} · {STATUS_LABELS.get(o.status, o.status)}{operator}{mark}"
        )
    lines.append("\nОберіть, про яке замовлення писати:")

    await message.answer("\n".join(lines), reply_markup=chat.pick_order_keyboard(open_orders))


async def _deliver(repo, user, text, order_id, bot=None, attachment=None) -> str:
    order = await repo.get_order(order_id)
    if not order or order.user_id != user.id:
        return "Це замовлення не знайдено."
    await chat.save_incoming(repo, order, user, text, bot=bot, attachment=attachment)
    await repo.set_chat_order(user.id, order.id)

    who = f" ({order.operator_name})" if order.operator_name else ""
    return f"Передали менеджеру{who} щодо замовлення №{order.id}. Відповідь надійде сюди."


@router.message(F.photo | F.document | F.video | F.voice)
async def incoming_file(
    message: Message, repo: Repository, user: User, state: FSMContext
) -> None:
    """Фото квитанції, скрин чи документ — теж частина розмови."""
    if await state.get_state() is not None:
        return

    attachment = chat.describe_attachment(message)
    if not attachment:
        return

    order_id = await chat.route_incoming(repo, user, message)
    if not order_id:
        open_orders = await chat.open_orders_for(repo, user.id)
        if not open_orders:
            await message.answer("Щоб надіслати файл менеджеру, потрібне активне замовлення.")
            return
        await message.answer(
            "Оберіть замовлення, до якого належить файл, і надішліть його ще раз.",
            reply_markup=chat.pick_order_keyboard(open_orders),
        )
        return

    caption = (message.caption or "").strip() or f"[{attachment['file_name']}]"
    await message.answer(
        await _deliver(repo, user, caption, order_id, message.bot, attachment)
    )


@router.message(F.text & ~F.text.startswith("/"))
async def incoming(
    message: Message, repo: Repository, user: User, state: FSMContext
) -> None:
    if await state.get_state() is not None:
        return

    text = (message.text or "").strip()
    if not text:
        return
    if len(text) > MAX_LENGTH:
        await message.answer(
            f"Повідомлення задовге — до {MAX_LENGTH} символів. "
            "Опишіть коротко, менеджер перепитає."
        )
        return

    # Відповідь на цитату — це свідоме звернення до менеджера, туди й веде.
    # На решту спершу пробуємо відповісти самі: типові питання не мають
    # чекати на людину, а менеджер не має відповідати на них удвадцяте.
    quoted = getattr(message, "reply_to_message", None) is not None
    if not quoted:
        shop = await get_shop_settings(repo)
        rule = faq.match(text, shop)
        if rule:
            await message.answer(
                faq.render(rule, shop),
                reply_markup=kb.faq_reply(with_shop=rule.with_shop),
            )
            return

    order_id = await chat.route_incoming(repo, user, message)
    if order_id:
        await message.answer(await _deliver(repo, user, text, order_id, message.bot))
        return

    open_orders = await chat.open_orders_for(repo, user.id)
    if not open_orders:
        await message.answer(
            "Щоб написати менеджеру, потрібне активне замовлення. "
            "Оформіть його в магазині — і зможете спитати тут."
        )
        return

    # Кілька відкритих замовлень і жодне не обране: просимо вибрати.
    # Текст не зберігаємо — просимо повторити після вибору, бо FSM у
    # serverless ненадійний, а мовчки загубити повідомлення гірше.
    await message.answer(
        "У вас кілька активних замовлень. Оберіть, до якого стосується "
        "повідомлення, і надішліть його ще раз.",
        reply_markup=chat.pick_order_keyboard(open_orders),
    )


@router.callback_query(F.data == "faq:human")
async def ask_human(callback: CallbackQuery, repo: Repository, user: User) -> None:
    """Клієнт хоче людину. Показуємо, куди писати, а не мовчимо."""
    open_orders = await chat.open_orders_for(repo, user.id)
    if not open_orders:
        await callback.message.answer(
            "Напишіть питання сюди — менеджер відповість. Якщо воно про "
            "конкретне замовлення, спершу оформіть його в магазині."
        )
    elif len(open_orders) == 1:
        await repo.set_chat_order(user.id, open_orders[0].id)
        await callback.message.answer(
            f"Пишіть — передамо менеджеру щодо замовлення №{open_orders[0].id}."
        )
    else:
        await callback.message.answer(
            "Оберіть замовлення, про яке питання:",
            reply_markup=chat.pick_order_keyboard(open_orders),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("chat:"))
async def pick_order(callback: CallbackQuery, repo: Repository, user: User) -> None:
    try:
        order_id = int(callback.data.split(":")[1])
    except (IndexError, ValueError):
        await callback.answer("Кнопка застаріла", show_alert=True)
        return

    order = await repo.get_order(order_id)
    if not order or order.user_id != user.id:
        await callback.answer("Замовлення не знайдено", show_alert=True)
        return

    await repo.set_chat_order(user.id, order.id)
    await callback.message.edit_text(_hint(order.id))
    await callback.answer()
