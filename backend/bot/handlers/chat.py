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
from shop.services import support_chat as support
from shop.services.shop_settings import get_shop_settings

router = Router(name="chat")

MAX_LENGTH = 2000


def _hint(order_id: int) -> str:
    return (
        f"Ви пишете щодо замовлення <b>№{order_id}</b>.\n"
        "Щоб перемкнутися на інше — /orders"
    )


def _support_intro() -> str:
    return (
        "🆘 <b>Менеджер / техпідтримка</b>\n\n"
        "Режим підтримки увімкнено. Усі наступні повідомлення, фото, "
        "скриншоти, документи, відео та голосові будуть передані менеджеру.\n\n"
        "Менеджер відповість прямо в цьому чаті Telegram. Поки звернення "
        "відкрите, звичайне меню приховане, щоб повідомлення випадково не "
        "потрапило в інший сценарій.\n\n"
        "Коли питання вирішено — натисніть «✅ Завершити звернення» або введіть /done."
    )


async def _answer_after_support_close(target, repo: Repository, user: User, text: str) -> None:
    """Повертає головне меню, не ламаючи вже створену наступну сесію.

    Aiogram може обробляти два апдейти одного клієнта майже одночасно:
    /done закрив старий thread, а наступний /ask уже встиг створити новий.
    Пізніша відповідь /done з main_menu не повинна заховати кнопку
    завершення нової сесії, тому після відправки ще раз звіряємо БД.
    """
    await target.answer(text, reply_markup=kb.main_menu())
    active = await repo.get_support_thread_for_user(user.id)
    if active:
        await target.answer(
            f"🆘 Звернення #{active.id} активне. Продовжуйте писати сюди.",
            reply_markup=support.support_keyboard(),
        )


@router.message(F.text == "🆘 Підтримка")
@router.message(Command("ask"))
async def start_support(message: Message, repo: Repository, user: User) -> None:
    """Відкриває загальну підтримку, яка працює лише в приватному чаті."""
    thread, created = await support.start(repo, user.id)
    if created:
        await message.answer(_support_intro(), reply_markup=support.support_keyboard())
    else:
        await message.answer(
            f"🆘 Звернення #{thread.id} вже відкрите. Продовжуйте писати сюди — "
            "нову сесію створювати не потрібно. Завершити її можна кнопкою нижче або /done.",
            reply_markup=support.support_keyboard(),
        )


@router.message(F.text == "✅ Завершити звернення")
@router.message(Command("done", "close"))
async def stop_support(message: Message, repo: Repository, user: User) -> None:
    closed, changed = await support.close(
        repo, user.id, closed_by="client",
        closed_by_name=user.first_name or (f"@{user.username}" if user.username else f"Telegram {user.tg_id}"),
        close_reason="done"
    )
    if not closed or not changed:
        await _answer_after_support_close(
            message, repo, user,
            "Зараз немає відкритого звернення до підтримки. Якщо потрібна допомога — /ask.",
        )
        return
    await _answer_after_support_close(
        message, repo, user,
        "✅ Звернення завершено. Історія збережена. Якщо з’явиться нове питання — "
        "натисніть «🆘 Підтримка» або введіть /ask.",
    )


@router.callback_query(F.data == "support:start")
async def start_support_button(
    callback: CallbackQuery, repo: Repository, user: User
) -> None:
    thread, created = await support.start(repo, user.id)
    await callback.message.answer(
        _support_intro() if created else
        f"🆘 Звернення #{thread.id} вже відкрите. Продовжуйте писати в ньому.",
        reply_markup=support.support_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "support:done")
async def stop_support_button(
    callback: CallbackQuery, repo: Repository, user: User
) -> None:
    closed, changed = await support.close(
        repo, user.id, closed_by="client",
        closed_by_name=user.first_name or (f"@{user.username}" if user.username else f"Telegram {user.tg_id}"),
        close_reason="done"
    )
    await _answer_after_support_close(
        callback.message, repo, user,
        "✅ Звернення завершено. Історія збережена. Якщо потрібна допомога ще раз — /ask."
        if closed and changed else
        "Відкритого звернення вже немає. Для нового питання використайте /ask.",
    )
    await callback.answer()


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

    if await support.is_active(repo, user.id):
        attachment = support.describe_attachment(message)
        if not attachment:
            return
        caption = (message.caption or "").strip() or f"[{attachment['file_name']}]"
        saved = await support.save_incoming(
            repo, user, caption, bot=message.bot, attachment=attachment
        )
        if saved is None:
            await message.answer(
                "Це звернення вже завершено. Файл не створив нову сесію автоматично. "
                "Якщо потрібна допомога — відкрийте нове звернення через /ask.",
                reply_markup=kb.main_menu(),
            )
            return
        await message.answer("Передали в підтримку. Менеджер відповість у цьому чаті.")
        return

    attachment = chat.describe_attachment(message)
    if not attachment:
        return

    order_id = await chat.route_incoming(repo, user, message)
    if not order_id:
        open_orders = await chat.open_orders_for(repo, user.id)
        if not open_orders:
            await message.answer(
                "Цей файл не вдалося прив’язати до замовлення. Якщо це загальне "
                "питання або технічна проблема, відкрийте підтримку кнопкою нижче.",
                reply_markup=chat.contact_options_keyboard([]),
            )
            return
        await message.answer(
            # Фото в магазин — це майже завжди квитанція, тож питаємо
            # прямо про замовлення, а не про абстрактний «файл».
            "До якого замовлення цей знімок? Оберіть кнопкою — і надішліть "
            "його ще раз.",
            reply_markup=chat.pick_order_keyboard(open_orders),
        )
        return

    caption = (message.caption or "").strip() or f"[{attachment['file_name']}]"
    delivered = await _deliver(repo, user, caption, order_id, message.bot, attachment)
    if attachment.get("file_kind") == "photo":
        # Бот не вміє читати суму зі знімка й не вдає, що вміє: обіцяти
        # автоматичну перевірку означало б, що людина чекатиме підтвердження,
        # якого ніхто не надішле.
        delivered += "\n\nМенеджер перевірить і підтвердить замовлення."
    await message.answer(delivered)


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

    # /ask відкриває окрему загальну стрічку. Поки вона відкрита, звичайні
    # повідомлення не повинні випадково піти в FAQ або в останнє замовлення.
    # Інакше клієнт думає, що пише техпідтримці, а текст опиняється не там.
    if await support.is_active(repo, user.id):
        saved = await support.save_incoming(repo, user, text, bot=message.bot)
        if saved is None:
            await message.answer(
                "Це звернення щойно було завершено. Повідомлення не відкривало старий чат "
                "і не створювало новий автоматично. Для нового питання введіть /ask.",
                reply_markup=kb.main_menu(),
            )
            return
        await message.answer("Передали в підтримку. Менеджер відповість у цьому чаті.")
        return

    # Відповідь на цитату — це свідоме звернення до менеджера, туди й веде.
    # На решту спершу пробуємо відповісти самі: типові питання не мають
    # чекати на людину, а менеджер не має відповідати на них удвадцяте.
    # Повідомлення про оплату довідка не перехоплює.
    #
    # «Оплачено» збігається з правилом про оплату за коренем «оплат», і
    # бот у відповідь пояснював, ЯК платити. Людина щойно переказала
    # гроші, а їй розповідають про накладений платіж — і жодного натяку,
    # що повідомлення кудись передали. Такі слова означають дію, яка вже
    # сталася, і належать менеджеру, а не автовідповідачу.
    claims_payment = faq.payment_claim(text)

    quoted = getattr(message, "reply_to_message", None) is not None
    if not quoted and not claims_payment:
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
        delivered = await _deliver(repo, user, text, order_id, message.bot)
        if claims_payment:
            # Окреме підтвердження саме про оплату. Людина, яка щойно
            # переказала гроші, чекає не «передали менеджеру», а відповіді
            # на своє питання: дійшло чи ні. Сказати, що перевірять
            # вручну, — чесніше, ніж мовчати: бот не бачить рахунку й
            # підтвердити оплату не може.
            delivered += ("\n\nМенеджер звірить надходження й підтвердить "
                          "замовлення. Якщо є квитанція — надішліть її сюди.")
        await message.answer(delivered)
        return

    open_orders = await chat.open_orders_for(repo, user.id)
    if not open_orders:
        await message.answer(
            "Не бачу активного замовлення, до якого можна прив’язати це повідомлення. "
            "Якщо питання загальне або вам потрібна техпідтримка — відкрийте окреме "
            "звернення. Замовлення для цього не потрібне.",
            reply_markup=chat.contact_options_keyboard([]),
        )
        return

    # Кілька відкритих замовлень і жодне не обране: просимо вибрати.
    # Текст не зберігаємо — просимо повторити після вибору, бо FSM у
    # serverless ненадійний, а мовчки загубити повідомлення гірше.
    await message.answer(
        "Яке саме замовлення оплачено? Оберіть кнопкою — і надішліть "
        "повідомлення ще раз, воно піде менеджеру цього замовлення."
        if claims_payment else
        "У вас кілька активних замовлень. Оберіть, до якого стосується "
        "повідомлення, і надішліть його ще раз.",
        reply_markup=chat.pick_order_keyboard(open_orders),
    )


@router.callback_query(F.data == "faq:human")
async def ask_human(callback: CallbackQuery, repo: Repository, user: User) -> None:
    """Явно показує, куди піде звернення: замовлення чи загальна підтримка."""
    orders = await chat.open_orders_for(repo, user.id)
    if orders:
        text = (
            "💬 <b>Що хочете уточнити?</b>\n\n"
            "📦 <b>Про конкретне замовлення</b> — натисніть його кнопку нижче. "
            "Відкриється чат саме цього замовлення, з номером та історією листування.\n\n"
            "🆘 <b>Інше питання або технічна проблема</b> — відкрийте загальну "
            "підтримку. Для неї замовлення не потрібне."
        )
    else:
        text = (
            "💬 <b>Написати менеджеру</b>\n\n"
            "Замовлень, для яких зараз доступний окремий чат, не знайдено. "
            "Якщо у вас загальне питання, проблема з магазином або потрібна "
            "допомога до оформлення замовлення — звертайтесь у підтримку.\n\n"
            "Натисніть кнопку нижче або введіть /ask — замовлення для цього не потрібне."
        )
    await callback.message.answer(
        text, reply_markup=chat.contact_options_keyboard(orders)
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

    # Явний перехід у чат замовлення завершує загальний режим /ask.
    # Інакше chat_order_id встановився б правильно, але наступне повідомлення
    # все одно перехопила б активна підтримка й воно пішло не туди.
    was_support = await support.is_active(repo, user.id)
    if was_support:
        await support.close(
            repo, user.id,
            closed_by="client",
            closed_by_name=user.first_name or (f"@{user.username}" if user.username else f"Telegram {user.tg_id}"),
            close_reason="order_switch",
        )
    await repo.set_chat_order(user.id, order.id)
    await callback.message.edit_text(_hint(order.id))
    if was_support:
        # Inline-кнопка могла бути натиснута зі старого повідомлення вже під
        # час /ask. Саме закриття сесії не змінює reply-клавіатуру Telegram,
        # тому явно повертаємо звичайне меню, інакше під полем вводу лишилась
        # би кнопка «Завершити звернення» вже після виходу з підтримки.
        await callback.message.answer(
            f"✅ Підтримку завершено. Тепер ви пишете щодо замовлення №{order.id}.",
            reply_markup=kb.main_menu(),
        )
    await callback.answer()
