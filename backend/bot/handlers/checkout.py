from __future__ import annotations

from shop.formatting import money as format_money
from shop.telegram_text import answer_html

import re
import secrets
import logging
from html import escape

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from bot import keyboards as kb
from bot import texts
from bot.states import Checkout
from shop.services.shop_settings import current
from shop.services.notifications import notify_new_order
from shop.services.shop_settings import get_shop_settings
from shop.entities import User
from shop.repo.base import Repository
from shop.services import shop_service as svc

router = Router()
log = logging.getLogger(__name__)



def normalize_phone(raw: str) -> str | None:
    """Той самий український формат, що приймає Mini App API.

    Старий бот пропускав будь-які 10–15 цифр, зокрема номер без коду
    країни, який потім не приймали CRM/перевізник.
    """
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("380"):
        body = digits[3:]
    elif digits.startswith("80") and len(digits) == 11:
        body = digits[2:]
    elif digits.startswith("0") and len(digits) == 10:
        body = digits[1:]
    else:
        body = digits
    if len(body) != 9 or not body or body[0] not in "3456789":
        return None
    return "+380" + body


@router.callback_query(F.data == "checkout")
async def start_checkout(
    callback: CallbackQuery, repo: Repository, user: User, state: FSMContext
) -> None:
    # Старе inline-повідомлення з кнопкою може лишатися в чаті. Подвійний
    # tap або повтор по старій кнопці не повинен запускати другу FSM-форму
    # і перезаписувати checkout_key активної спроби.
    active_state = await state.get_state()
    if active_state and active_state != Checkout.receipt.state:
        await callback.answer("Оформлення вже розпочато", show_alert=True)
        return

    problems = await svc.validate_cart(repo, user.id)
    if problems:
        await callback.answer("Змінилася наявність, перевірте кошик", show_alert=True)
        return
    if not await repo.get_cart(user.id):
        await callback.answer("Кошик порожній", show_alert=True)
        return

    # Очікування квитанції стосується вже створеного замовлення й не
    # повинно блокувати нову покупку. Квитанцію старого замовлення можна
    # надіслати через його чат.
    await state.clear()

    # Один ключ на одну спробу оформлення. Якщо Telegram доставить два
    # callback-и від швидкого подвійного натискання «Підтвердити», обидва
    # потраплять у той самий idempotent checkout замість двох замовлень.
    await state.update_data(checkout_key=f"bot_{user.id}_{secrets.token_urlsafe(16)}")
    await _show_step(callback.message, state, repo, user, "name")
    await callback.answer()


# Every prompt has its own token. Re-entering the same field invalidates all
# earlier buttons, including those from another checkout in this chat.
FIELDS = ("name", "phone", "city", "address", "promo", "bonus", "payment", "comment")
STALE = "Ця кнопка застаріла. Використайте останнє повідомлення оформлення"


def _value(data, field):
    value = data.get("use_bonus" if field == "bonus" else field)
    if field == "bonus":
        return "використовувати" if value else "не використовувати"
    if field == "payment":
        return "переказ на картку" if value == "card" else "накладений платіж"
    return str(value or "не вказано")


async def _show_step(message, state, repo, user, field):
    data = await state.get_data()
    if field == "bonus":
        try:
            quote = await svc.checkout_quote(repo, user, promo_code=data.get("promo"))
        except svc.CheckoutQuoteError as exc:
            await _quote_error(message, state, data, str(exc), kind=exc.kind)
            return
        if quote.bonus_available <= 0:
            await state.update_data(use_bonus=False)
            if data.get("editing"):
                await message.answer("Для цього замовлення немає доступних бонусів.")
                await _show_summary(message, state, repo, user)
            else:
                await _show_step(message, state, repo, user, "payment")
            return
        text = (f"На це замовлення можна списати до {format_money(quote.bonus_available)} {escape(quote.currency)}.\n"
                "Ліміт уже враховує знижку.")
        choices = [("Списати бонуси", "bonusyes"), ("Не використовувати", "bonusno")]
    elif field == "payment":
        text = "Оберіть спосіб оплати:"
        choices = [("💳 Переказ на картку", "paycard"), ("📦 Накладений платіж", "paycod")]
    else:
        text = getattr(texts, "CHECKOUT_" + field.upper())
        choices = []
        if field == "promo":
            choices.append(("Прибрати промокод" if data.get("promo") else "Пропустити", "skip"))
        elif field == "comment":
            choices.append(("Без коментаря", "skip"))
    key = "use_bonus" if field == "bonus" else field
    if key in data:
        text += "\n\nЗараз: <b>" + escape(_value(data, field)) + "</b>"
        choices.append(("Залишити як є", "keep"))
    token = secrets.token_hex(8)
    await state.update_data(step_id=token, step_field=field, confirmation_id=None, quote_token=None)
    await state.set_state(getattr(Checkout, field))
    rows = [[InlineKeyboardButton(text=label, callback_data=f"checkout:{action}:{token}")] for label, action in choices]
    if field != "name" or data.get("editing"):
        rows.append([InlineKeyboardButton(text="⬅️ До підсумку" if data.get("editing") else "⬅️ Назад", callback_data=f"checkout:back:{token}")])
    rows.append([InlineKeyboardButton(text="❌ Скасувати оформлення", callback_data=f"checkout:cancel:{token}")])
    if field == "phone":
        await message.answer(text, reply_markup=kb.PHONE_REQUEST)
        await message.answer("Керування оформленням:", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    else:
        # Remove a lingering contact keyboard when leaving the phone step.
        if field in ("name", "city") or data.get("step_field") == "phone":
            await message.answer("Продовжуємо оформлення.", reply_markup=ReplyKeyboardRemove())
        await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def _advance(message, state, repo, user, field):
    data = await state.get_data()
    if data.get("editing") or field == "comment":
        await _show_summary(message, state, repo, user)
    else:
        await _show_step(message, state, repo, user, FIELDS[FIELDS.index(field) + 1])


@router.message(StateFilter(*(getattr(Checkout, f) for f in FIELDS), Checkout.confirm), Command("cancel"))
async def cancel_checkout_command(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Оформлення скасовано. Кошик залишився без змін.", reply_markup=kb.main_menu())


@router.callback_query(F.data.startswith("checkout:"))
async def checkout_navigation(callback: CallbackQuery, state: FSMContext, repo: Repository, user: User):
    data = await state.get_data()
    parts = callback.data.split(":")
    field = data.get("step_field")
    if (len(parts) != 3 or not data.get("step_id") or parts[2] != data["step_id"]
            or field not in FIELDS or await state.get_state() != getattr(Checkout, field).state):
        await callback.answer(STALE, show_alert=True)
        return
    action = parts[1]
    if action == "cancel":
        await state.clear()
        await callback.message.answer("Оформлення скасовано. Кошик залишився без змін.", reply_markup=kb.main_menu())
    elif action == "back":
        if data.get("editing"):
            await _show_summary(callback.message, state, repo, user)
        elif field != "name":
            previous = FIELDS[FIELDS.index(field) - 1]
            # The bonus step may have been skipped because its limit is zero.
            if field == "payment":
                try:
                    quote = await svc.checkout_quote(repo, user, promo_code=data.get("promo"))
                except svc.CheckoutQuoteError as exc:
                    await _quote_error(callback.message, state, data, str(exc), kind=exc.kind)
                    await callback.answer()
                    return
                if quote.bonus_available <= 0:
                    previous = "promo"
            await _show_step(callback.message, state, repo, user, previous)
    elif action == "keep" and ("use_bonus" if field == "bonus" else field) in data:
        # Promo validity and bonus limits are checked afresh on the next quote.
        await _advance(callback.message, state, repo, user, field)
    elif action == "skip" and field in ("promo", "comment"):
        await state.update_data(**({"promo": None, "discount": "0"} if field == "promo" else {"comment": None}))
        await _advance(callback.message, state, repo, user, field)
    elif action in ("bonusyes", "bonusno") and field == "bonus":
        await state.update_data(use_bonus=action == "bonusyes")
        await _advance(callback.message, state, repo, user, field)
    elif action in ("paycard", "paycod") and field == "payment":
        await state.update_data(payment="card" if action == "paycard" else "cod")
        await _advance(callback.message, state, repo, user, field)
    else:
        await callback.answer(STALE, show_alert=True)
        return
    await callback.answer()


@router.message(Checkout.name, F.text, ~F.text.startswith("/"))
async def step_name(message: Message, state: FSMContext, repo: Repository = None, user: User = None) -> None:
    name = message.text.strip()
    if not 3 <= len(name) <= 128:
        await message.answer("Введіть ім'я та прізвище повністю: від 3 до 128 символів.")
        return
    await state.update_data(name=name)
    await _advance(message, state, repo, user, "name")


@router.message(Checkout.phone, F.contact)
async def step_phone_contact(message: Message, state: FSMContext, repo: Repository, user: User) -> None:
    await _save_phone(message, state, repo, user, message.contact.phone_number)


@router.message(Checkout.phone, F.text, ~F.text.startswith("/"))
async def step_phone_text(message: Message, state: FSMContext, repo: Repository, user: User) -> None:
    await _save_phone(message, state, repo, user, message.text)


async def _save_phone(message, state, repo, user, raw):
    phone = normalize_phone(raw)
    if not phone:
        await message.answer("Схоже, номер неповний. Приклад: 0671234567")
        return
    await state.update_data(phone=phone)
    await message.answer("Номер збережено.", reply_markup=ReplyKeyboardRemove())
    await _advance(message, state, repo, user, "phone")


@router.message(Checkout.city, F.text, ~F.text.startswith("/"))
async def step_city(message: Message, state: FSMContext, repo: Repository = None, user: User = None) -> None:
    city = message.text.strip()
    if not 1 <= len(city) <= 128:
        await message.answer("Вкажіть місто: від 1 до 128 символів.")
        return
    await state.update_data(city=city)
    await _advance(message, state, repo, user, "city")


@router.message(Checkout.address, F.text, ~F.text.startswith("/"))
async def step_address(message: Message, state: FSMContext, repo: Repository = None, user: User = None) -> None:
    address = message.text.strip()
    if not 1 <= len(address) <= 255:
        await message.answer("Вкажіть відділення або адресу: від 1 до 255 символів.")
        return
    await state.update_data(address=address)
    await _advance(message, state, repo, user, "address")


@router.message(Checkout.promo, F.text, ~F.text.startswith("/"))
async def step_promo(message: Message, state: FSMContext, repo: Repository, user: User) -> None:
    subtotal = await svc.cart_subtotal(repo, user.id)
    result = await svc.check_promo(repo, message.text, user.id, subtotal)
    if not result.ok:
        await message.answer(f"{escape(result.error)}. Спробуйте інший код або скористайтеся кнопкою пропуску в останньому повідомленні.")
        return
    await state.update_data(promo=result.promo.code, discount=str(result.discount))
    await message.answer(f"Промокод застосовано: −{format_money(result.discount)} грн")
    await _advance(message, state, repo, user, "promo")


@router.message(Checkout.comment, F.text, ~F.text.startswith("/"))
async def step_comment(message: Message, state: FSMContext, repo: Repository, user: User) -> None:
    if len(message.text.strip()) > 500:
        await message.answer("Скоротіть коментар до 500 символів.")
        return
    await state.update_data(comment=message.text.strip() or None)
    await _advance(message, state, repo, user, "comment")


# Pre-upgrade inline prompts have no token. Refresh the current prompt rather
# than interpreting an old unscoped skip/pay/bonus button in a new checkout.
@router.callback_query(F.data == "skip")
@router.callback_query(F.data.startswith("pay:"))
@router.callback_query(F.data.startswith("bonus:"))
async def legacy_step(callback: CallbackQuery, state: FSMContext, repo: Repository, user: User):
    data = await state.get_data()
    active = await state.get_state()
    field = next((f for f in FIELDS if active == getattr(Checkout, f).state), None)
    if field and not data.get("step_id"):
        await _show_step(callback.message, state, repo, user, field)
        await callback.answer("Кнопки оновлено. Продовжіть у новому повідомленні")
    else:
        await callback.answer(STALE, show_alert=True)


async def _show_summary(message: Message, state: FSMContext, repo: Repository, user: User) -> None:
    data = await state.get_data()
    if data.get("step_field") == "phone":
        await message.answer("Перевіряємо замовлення.", reply_markup=ReplyKeyboardRemove())
    try:
        quote = await svc.checkout_quote(repo, user, promo_code=data.get("promo"),
                                         use_bonus=bool(data.get("use_bonus")))
    except svc.CheckoutQuoteError as exc:
        await _quote_error(message, state, data, str(exc), kind=exc.kind)
        return
    items = quote.lines
    subtotal, discount, bonus, total = quote.subtotal, quote.discount, quote.bonus_used, quote.total
    currency = escape(quote.currency)
    confirmation_id = secrets.token_hex(8)
    await state.update_data(quote_token=quote.token, confirmation_id=confirmation_id,
                            step_id=None, step_field=None, editing=False)

    lines = ["<b>Перевірте замовлення</b>\n"]
    for line in items:
        lines.append(f"• {escape(line.product.name)} × {line.qty} — {format_money(line.line_total)} {currency}")
    lines.append(f"\nСума: {format_money(subtotal)} {currency}")
    if discount:
        label = "Знижка за суму" if quote.discount_source == "volume" else f"Промокод {escape(str(data.get('promo') or ''))}"
        lines.append(f"{label}: −{format_money(discount)} {currency}")
    if bonus:
        lines.append(f"Бонуси: −{format_money(bonus)} {currency}")
    lines.append(f"<b>До сплати: {format_money(total)} {currency}</b>\n")
    lines.append(f"Отримувач: {escape(str(data.get('name') or ''))}")
    lines.append(f"Телефон: {escape(str(data.get('phone') or ''))}")
    lines.append(f"Доставка: {escape(str(data.get('city') or ''))}, {escape(str(data.get('address') or ''))}")
    lines.append("Оплата: " + ("переказ на картку" if data.get("payment") == "card" else "накладений платіж"))
    if data.get("comment"):
        lines.append(f"Коментар: {escape(str(data['comment']))}")

    await state.set_state(Checkout.confirm)
    await answer_html(message, "\n".join(lines), reply_markup=kb.confirm_order(confirmation_id))


async def _quote_error(message, state, data, error, kind="cart"):
    await state.update_data(quote_token=None, confirmation_id=None, step_id=None)
    if kind == "promo":
        # Re-enter a tokenized prompt; all other checkout data stays intact.
        await message.answer(escape(error) + ". Введіть інший промокод або пропустіть крок.")
        await _show_step(message, state, None, None, "promo")
    else:
        await state.set_state(Checkout.confirm)
        confirmation_id = secrets.token_hex(8)
        await state.update_data(confirmation_id=confirmation_id)
        await message.answer(escape(error) + ". Перевірте кошик перед оформленням.",
                             reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                                 [InlineKeyboardButton(text="🛒 Кошик", callback_data="cart")],
                                 [InlineKeyboardButton(text="Оновити підсумок", callback_data=f"order:refresh:{confirmation_id}")],
                                 [InlineKeyboardButton(text="❌ Вийти з оформлення", callback_data=f"order:cancel:{confirmation_id}")],
                             ]))


def _current_confirmation(callback, data):
    suffix = callback.data.rsplit(":", 1)[-1]
    return bool(data.get("confirmation_id") and suffix == data["confirmation_id"])


@router.callback_query(Checkout.confirm, F.data.startswith("order:edit:"))
async def edit_order(callback: CallbackQuery, state: FSMContext, repo: Repository, user: User):
    data = await state.get_data()
    if not _current_confirmation(callback, data):
        await callback.answer(STALE, show_alert=True)
        return
    parts = callback.data.split(":")
    field = parts[2] if len(parts) == 4 else None
    if field not in FIELDS:
        await callback.answer(STALE, show_alert=True)
        return
    await state.update_data(editing=True)
    await _show_step(callback.message, state, repo, user, field)
    await callback.answer()


@router.callback_query(Checkout.confirm, F.data.startswith("order:refresh:"))
async def refresh_summary(callback: CallbackQuery, state: FSMContext, repo: Repository, user: User):
    if not _current_confirmation(callback, await state.get_data()):
        await callback.answer(STALE, show_alert=True)
        return
    await _show_summary(callback.message, state, repo, user)
    await callback.answer()


@router.callback_query(Checkout.confirm, F.data.startswith("order:cancel"))
async def cancel_order(callback: CallbackQuery, state: FSMContext) -> None:
    if not _current_confirmation(callback, await state.get_data()):
        await callback.answer("Ця кнопка застаріла. Використайте останній підсумок", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text("Замовлення скасовано. Кошик залишився без змін.")
    await callback.message.answer(texts.MENU_HINT, reply_markup=kb.main_menu())
    await callback.answer()


@router.callback_query(Checkout.confirm, F.data.startswith("order:confirm"))
async def confirm_order(
    callback: CallbackQuery, state: FSMContext, repo: Repository, user: User
) -> None:
    data = await state.get_data()
    if not _current_confirmation(callback, data):
        # Migrate a pre-update FSM summary without buying at an unseen total.
        if callback.data == "order:confirm" and not data.get("confirmation_id"):
            await _show_summary(callback.message, state, repo, user)
            await callback.answer("Перевірте оновлений підсумок")
            return
        await callback.answer("Ця кнопка застаріла. Використайте останній підсумок", show_alert=True)
        return
    if not data.get("quote_token"):
        await _show_summary(callback.message, state, repo, user)
        await callback.answer("Перевірте підсумок")
        return
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
        checkout_key=data.get("checkout_key"),
        expected_quote=data.get("quote_token"),
    )

    if error:
        # Keep contact fields and show a fresh quote for explicit reconfirmation.
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(f"Не вдалося оформити замовлення.\n\n{escape(error)}")
        await _show_summary(callback.message, state, repo, user)
        await callback.answer()
        return

    # Два callback-и можуть увійти в handler майже одночасно ще до зміни
    # FSM state. Другий отримає той самий Order за checkout_key; не шлемо
    # повторно PAYMENT_INFO і сповіщення менеджеру.
    if getattr(order, "checkout_replayed", False):
        await state.update_data(order_id=order.id, completed_confirmation_id=data["confirmation_id"])
        await state.set_state(Checkout.receipt if order.payment_method == "card" and order.total > 0 else None)
        await callback.answer("Замовлення вже оформлено")
        return

    shop = await get_shop_settings(repo)
    # Persist receipt / replay state before Telegram I/O: an edit failure must
    # not leave a successfully committed order in Checkout.confirm.
    await state.update_data(order_id=order.id, completed_confirmation_id=data["confirmation_id"])
    if order.payment_method == "card" and order.total > 0:
        await state.set_state(Checkout.receipt)
    else:
        await state.set_state(None)
    try:
        await notify_new_order(callback.bot, repo, order, user)
    except Exception:
        # Замовлення вже записане. Збій Telegram-сповіщення менеджеру не
        # повинен залишати клієнту нескінченний spinner і провокувати повтор.
        log.exception(
            "Замовлення №%s створено, але менеджер не отримав сповіщення", order.id
        )
    try:
        confirmation = texts.ORDER_DONE.format(id=order.id, total=format_money(order.total), currency=escape(shop.currency))
        try:
            await callback.message.edit_text(confirmation)
        except Exception:
            await callback.message.answer(confirmation)
        if order.payment_method == "card" and order.total > 0:
            await callback.message.answer(texts.PAYMENT_INFO.format(total=format_money(order.total), currency=escape(shop.currency)))
        else:
            await callback.message.answer(texts.MENU_HINT, reply_markup=kb.main_menu())
    except Exception:
        log.exception("Замовлення №%s створено, але підтвердження клієнту не доставлено", order.id)
    await callback.answer()


@router.callback_query(F.data.startswith("order:confirm"))
async def completed_confirmation(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    suffix = callback.data.rsplit(":", 1)[-1]
    if data.get("order_id") and suffix == data.get("completed_confirmation_id"):
        await callback.answer(f"Замовлення №{data['order_id']} вже оформлено")
    else:
        await callback.answer("Ця кнопка застаріла. Відкрийте останній підсумок", show_alert=True)


@router.callback_query(F.data.startswith("order:edit:"))
@router.callback_query(F.data.startswith("order:cancel"))
@router.callback_query(F.data.startswith("order:refresh:"))
async def stale_summary_action(callback: CallbackQuery):
    await callback.answer(STALE, show_alert=True)


@router.message(Checkout.receipt, F.photo | F.document)
async def receive_receipt(message: Message, state: FSMContext, repo: Repository, user: User) -> None:
    from shop.services import order_chat
    from shop.services.panel_notifications import safe_publish
    from shop.services.notifications import notify_receipt

    data = await state.get_data()
    attachment = order_chat.describe_attachment(message)
    try:
        saved = await repo.save_order_receipt(
            data.get("order_id"), user.id, attachment,
            tg_message_id=message.message_id,
            author=user.first_name or user.username or f"id{user.tg_id}",
            text="Квитанція" + (": " + message.caption if message.caption else ""),
        )
    except Exception:
        log.exception("Не вдалося зберегти квитанцію до замовлення №%s", data.get("order_id"))
        await message.answer("Не вдалося зберегти квитанцію. Надішліть файл ще раз — замовлення збережене.")
        return
    if saved is None:
        await message.answer("Не вдалося прив’язати квитанцію: замовлення недоступне для оплати. Для допомоги — /ask.")
        return
    # The file and visible chat entry committed together before any external I/O.
    await state.clear()
    await safe_publish(repo, "order.message", f"Квитанція до замовлення №{data['order_id']}",
                       saved.text, href=f"/orders/{data['order_id']}",
                       entity_id=data['order_id'], actor=saved.author)
    try:
        order = await repo.get_order(data['order_id'])
        await notify_receipt(message.bot, repo, order, attachment)
    except Exception:
        log.exception("Квитанція №%s збережена, але Telegram-сповіщення не доставлено", data['order_id'])
    await message.answer("Квитанцію збережено в замовленні. Менеджер перевірить оплату.", reply_markup=kb.main_menu())


@router.message(Checkout.receipt, Command("ask"))
@router.message(Checkout.receipt, F.text == "🆘 Підтримка")
async def receipt_support(message: Message, state: FSMContext, repo: Repository, user: User):
    from bot.handlers.chat import start_support
    await state.clear()
    await start_support(message, repo, user)


@router.message(Checkout.receipt, ~F.text.startswith("/"), ~F.text.in_({"👤 Профіль", "🆘 Підтримка", "✅ Завершити звернення"}))
async def receipt_hint(message: Message):
    await message.answer("Надішліть квитанцію як фото або документ, наприклад PDF. Для допомоги — /ask.")
