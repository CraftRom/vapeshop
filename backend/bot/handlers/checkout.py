from __future__ import annotations

import re
from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove
from bot import keyboards as kb
from bot import texts
from bot.states import Checkout
from shop.config import settings
from shop.services.shop_settings import get_shop_settings
from shop.entities import Order, User
from shop.repo.base import Repository
from shop.services import shop_service as svc

router = Router()

PHONE_RE = re.compile(r"^\+?\d{10,15}$")


def normalize_phone(raw: str) -> str | None:
    digits = re.sub(r"[^\d+]", "", raw or "")
    if digits.startswith("0") and len(digits) == 10:
        digits = "+38" + digits
    elif digits.startswith("38") and len(digits) == 12:
        digits = "+" + digits
    return digits if PHONE_RE.match(digits) else None


@router.callback_query(F.data == "checkout")
async def start_checkout(
    callback: CallbackQuery, repo: Repository, user: User, state: FSMContext
) -> None:
    problems = await svc.validate_cart(repo, user.id)
    if problems:
        await callback.answer("Змінилася наявність, перевірте кошик", show_alert=True)
        return
    if not await repo.get_cart(user.id):
        await callback.answer("Кошик порожній", show_alert=True)
        return

    await state.set_state(Checkout.name)
    await callback.message.answer(texts.CHECKOUT_NAME, reply_markup=ReplyKeyboardRemove())
    await callback.answer()


@router.message(Checkout.name, F.text)
async def step_name(message: Message, state: FSMContext) -> None:
    name = message.text.strip()
    if len(name) < 3:
        await message.answer("Введіть ім'я та прізвище повністю.")
        return
    await state.update_data(name=name)
    await state.set_state(Checkout.phone)
    await message.answer(texts.CHECKOUT_PHONE, reply_markup=kb.PHONE_REQUEST)


@router.message(Checkout.phone, F.contact)
async def step_phone_contact(message: Message, state: FSMContext) -> None:
    await state.update_data(phone=message.contact.phone_number)
    await state.set_state(Checkout.city)
    await message.answer(texts.CHECKOUT_CITY, reply_markup=ReplyKeyboardRemove())


@router.message(Checkout.phone, F.text)
async def step_phone_text(message: Message, state: FSMContext) -> None:
    phone = normalize_phone(message.text)
    if not phone:
        await message.answer("Схоже, номер неповний. Приклад: 0671234567")
        return
    await state.update_data(phone=phone)
    await state.set_state(Checkout.city)
    await message.answer(texts.CHECKOUT_CITY, reply_markup=ReplyKeyboardRemove())


@router.message(Checkout.city, F.text)
async def step_city(message: Message, state: FSMContext) -> None:
    await state.update_data(city=message.text.strip())
    await state.set_state(Checkout.address)
    await message.answer(texts.CHECKOUT_ADDRESS)


@router.message(Checkout.address, F.text)
async def step_address(message: Message, state: FSMContext) -> None:
    await state.update_data(address=message.text.strip())
    await state.set_state(Checkout.promo)
    await message.answer(texts.CHECKOUT_PROMO, reply_markup=kb.SKIP)


@router.message(Checkout.promo, F.text)
async def step_promo(message: Message, state: FSMContext, repo: Repository, user: User) -> None:
    subtotal = await svc.cart_subtotal(repo, user.id)
    result = await svc.check_promo(repo, message.text, user.id, subtotal)
    if not result.ok:
        await message.answer(f"{result.error}. Спробуйте інший код або пропустіть крок.", reply_markup=kb.SKIP)
        return
    await state.update_data(promo=result.promo.code, discount=str(result.discount))
    await message.answer(f"Промокод застосовано: −{result.discount:.0f} грн")
    await _ask_bonus(message, state, repo, user)


@router.callback_query(Checkout.promo, F.data == "skip")
async def skip_promo(callback: CallbackQuery, state: FSMContext, repo: Repository, user: User) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await _ask_bonus(callback.message, state, repo, user)
    await callback.answer()


async def _ask_bonus(message: Message, state: FSMContext, repo: Repository, user: User) -> None:
    data = await state.get_data()
    subtotal = await svc.cart_subtotal(repo, user.id)
    discount = Decimal(data.get("discount", "0"))
    available = await svc.max_bonus_for_repo(repo, subtotal - discount, user.bonus_balance)

    if available <= 0:
        await state.set_state(Checkout.payment)
        await message.answer("Оберіть спосіб оплати:", reply_markup=kb.payment_methods())
        return

    await state.set_state(Checkout.bonus)
    await message.answer(
        f"На вашому бонусному рахунку {user.bonus_balance:.0f} грн.\n"
        f"На це замовлення можна списати до {available:.0f} грн.",
        reply_markup=kb.bonus_prompt(available),
    )


@router.callback_query(Checkout.bonus, F.data.startswith("bonus:"))
async def step_bonus(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(use_bonus=callback.data.endswith("yes"))
    await state.set_state(Checkout.payment)
    await callback.message.edit_text("Оберіть спосіб оплати:", reply_markup=kb.payment_methods())
    await callback.answer()


@router.callback_query(Checkout.payment, F.data.startswith("pay:"))
async def step_payment(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(payment=callback.data.split(":")[1])
    await state.set_state(Checkout.comment)
    await callback.message.edit_text(texts.CHECKOUT_COMMENT, reply_markup=kb.SKIP)
    await callback.answer()


@router.message(Checkout.comment, F.text)
async def step_comment(message: Message, state: FSMContext, repo: Repository, user: User) -> None:
    await state.update_data(comment=message.text.strip())
    await _show_summary(message, state, repo, user)


@router.callback_query(Checkout.comment, F.data == "skip")
async def skip_comment(callback: CallbackQuery, state: FSMContext, repo: Repository, user: User) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await _show_summary(callback.message, state, repo, user)
    await callback.answer()


async def _show_summary(message: Message, state: FSMContext, repo: Repository, user: User) -> None:
    data = await state.get_data()
    items = await repo.get_cart(user.id)
    subtotal = sum((i.product.price * i.qty for i in items), Decimal(0))
    discount = Decimal(data.get("discount", "0"))
    bonus = (
        await svc.max_bonus_for_repo(repo, subtotal - discount, user.bonus_balance)
        if data.get("use_bonus") else Decimal(0)
    )
    total = max(Decimal(0), subtotal - discount - bonus)

    lines = ["<b>Перевірте замовлення</b>\n"]
    for line in items:
        lines.append(f"• {line.product.name} × {line.qty} — {line.line_total:.0f} грн")
    lines.append(f"\nСума: {subtotal:.0f} грн")
    if discount:
        lines.append(f"Промокод {data.get('promo')}: −{discount:.0f} грн")
    if bonus:
        lines.append(f"Бонуси: −{bonus:.0f} грн")
    lines.append(f"<b>До сплати: {total:.0f} грн</b>\n")
    lines.append(f"Отримувач: {data.get('name')}")
    lines.append(f"Телефон: {data.get('phone')}")
    lines.append(f"Доставка: {data.get('city')}, {data.get('address')}")
    lines.append("Оплата: " + ("переказ на картку" if data.get("payment") == "card" else "накладений платіж"))
    if data.get("comment"):
        lines.append(f"Коментар: {data['comment']}")

    await state.set_state(Checkout.confirm)
    await message.answer("\n".join(lines), reply_markup=kb.confirm_order())


@router.callback_query(Checkout.confirm, F.data == "order:cancel")
async def cancel_order(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Замовлення скасовано. Кошик залишився без змін.")
    await callback.message.answer(texts.MENU_HINT, reply_markup=kb.MAIN_MENU)
    await callback.answer()


@router.callback_query(Checkout.confirm, F.data == "order:confirm")
async def confirm_order(
    callback: CallbackQuery, state: FSMContext, repo: Repository, user: User
) -> None:
    data = await state.get_data()
    order, error = await svc.create_order(
        repo,
        user,
        contact_name=data["name"],
        contact_phone=data["phone"],
        city=data["city"],
        address=data["address"],
        payment_method=data.get("payment", "card"),
        comment=data.get("comment"),
        promo_code=data.get("promo"),
        use_bonus=bool(data.get("use_bonus")),
    )

    if error:
        await state.clear()
        await callback.message.edit_text(f"Не вдалося оформити замовлення.\n\n{error}")
        await callback.answer()
        return

    shop = await get_shop_settings(repo)
    await callback.message.edit_text(
        texts.ORDER_DONE.format(id=order.id, total=f"{order.total:.0f}", currency=shop.currency)
    )

    if order.payment_method == "card" and order.total > 0:
        await state.set_state(Checkout.receipt)
        await state.update_data(order_id=order.id)
        await callback.message.answer(
            texts.PAYMENT_INFO.format(
                card=shop.card_number,
                holder=shop.card_holder or "—",
                total=f"{order.total:.0f}",
                currency=shop.currency,
            )
        )
    else:
        await state.clear()
        await callback.message.answer(texts.MENU_HINT, reply_markup=kb.MAIN_MENU)

    await _notify_admins(callback, order, user)
    await callback.answer()


@router.message(Checkout.receipt, F.photo)
async def receive_receipt(message: Message, state: FSMContext, repo: Repository) -> None:
    data = await state.get_data()
    order = await repo.get_order(data.get("order_id"))
    if order:
        await repo.update_order(order.id, {"receipt_file_id": message.photo[-1].file_id})
        if settings.admin_chat_id:
            await message.bot.send_photo(
                settings.admin_chat_id,
                message.photo[-1].file_id,
                caption=f"Квитанція до замовлення №{order.id}",
                reply_markup=kb.admin_order(order.id),
            )
    await state.clear()
    await message.answer("Квитанцію отримано. Менеджер перевірить оплату.", reply_markup=kb.MAIN_MENU)


async def _notify_admins(callback: CallbackQuery, order: Order, user: User) -> None:
    if not settings.admin_chat_id:
        return
    items = "\n".join(f"• {ln.name} × {ln.qty} — {ln.line_total:.0f} грн" for ln in order.items)
    username = f"@{user.username}" if user.username else f"id{user.tg_id}"
    text = (
        f"🆕 <b>Замовлення №{order.id}</b>\n\n"
        f"{items}\n\n"
        f"Сума: {order.subtotal:.0f} грн\n"
        f"Знижка: {order.discount:.0f} грн | Бонуси: {order.bonus_used:.0f} грн\n"
        f"<b>До сплати: {order.total:.0f} грн</b>\n\n"
        f"Клієнт: {order.contact_name} ({username})\n"
        f"Телефон: {order.contact_phone}\n"
        f"Доставка: {order.delivery_city}, {order.delivery_address}\n"
        f"Оплата: {'картка' if order.payment_method == 'card' else 'накладений платіж'}"
    )
    if order.comment:
        text += f"\nКоментар: {order.comment}"
    await callback.bot.send_message(settings.admin_chat_id, text, reply_markup=kb.admin_order(order.id))
