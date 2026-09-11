from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup,
    WebAppInfo,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shop.links import app_link, chat_link, share_link
from shop.entities import OrderStatus
from shop.services.shop_service import route_for
from shop.services.shop_settings import current
from shop.models import CartItem, Category, Product

# ------------------------------------------------------------------ головне меню

def _shop_url() -> str | None:
    """Адреса вітрини. Без PUBLIC_URL кнопку показати не можна.

    Зі слешем на кінці навмисно: Telegram на Android кешує WebView міні-аппа
    за адресою, і при відновленні процесу перезавантажує вже обрізану версію
    посилання — без підпису користувача. Зміна адреси змушує клієнт відкрити
    сторінку з нуля. Обидві форми, /app і /app/, ведуть в одне місце.
    """
    public_url = current().public_url
    if not public_url:
        return None
    return public_url.rstrip("/") + "/app/"


def to_private_chat() -> InlineKeyboardMarkup:
    """Кнопка з групи/каналу в особистий чат.

    Веде на deep link бота: у приватному чаті одразу спрацює /start.
    Кнопка з web_app тут не годиться — Telegram дозволяє її лише в приватних
    чатах, у групі повідомлення просто не надішлеться.
    """
    # Пряме посилання на вітрину, якщо застосунок зареєстровано;
    # інакше — просто в особистий чат
    url = app_link("group") or chat_link("group")
    if not url:
        return InlineKeyboardMarkup(inline_keyboard=[])
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🛍 Відкрити магазин", url=url)]]
    )


def faq_reply(with_shop: bool = True) -> InlineKeyboardMarkup | None:
    """Кнопки під автоматичною відповіддю.

    «Питання менеджеру» обовʼязкова: автовідповідь не має ставати глухим
    кутом, якщо клієнт питав не те, що ми зрозуміли.
    """
    rows = []
    url = _shop_url()
    if with_shop and url:
        rows.append([InlineKeyboardButton(text="🛍 Відкрити магазин", web_app=WebAppInfo(url=url))])
    rows.append([InlineKeyboardButton(text="💬 Питання менеджеру", callback_data="faq:human")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def open_shop() -> InlineKeyboardMarkup | None:
    """Кнопка вітрини під самим повідомленням.

    Другий вхід поруч із кнопкою в клавіатурі — і він потрібен, а не
    надлишковий. Кнопка з web_app у клавіатурі під полем вводу на частині
    клієнтів просто не спрацьовує: натискання є, застосунок не
    відкривається. Синя кнопка «Магазин» біля поля вводу при цьому працює,
    тобто справа не в адресі й не в домені бота.

    Вбудована кнопка під повідомленням — найнадійніший із трьох входів:
    її підтримують усі клієнти, які взагалі вміють Mini App. Тому вітальне
    повідомлення тепер несе її з собою, і людині не треба знати, що є
    якась синя кнопка збоку.
    """
    url = _shop_url()
    if not url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Відкрити магазин", web_app=WebAppInfo(url=url))]
    ])


def main_menu() -> ReplyKeyboardMarkup:
    """Головне меню.

    Коли вітрина налаштована, лишається одна кнопка — Mini App. Каталог,
    кошик і профіль там уже є, і дублювати їх текстовими кнопками означало б
    два різні шляхи до одного й того самого, які легко розійдуться.

    «Довідка» лишається: її у вітрині немає.

    Без PUBLIC_URL кнопку Mini App показати неможливо, тож меню повертається
    до текстового вигляду — інакше в користувача не лишиться взагалі нічого.
    """
    url = _shop_url()
    if url:
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🛍 Відкрити магазин", web_app=WebAppInfo(url=url))],
                [KeyboardButton(text="🆘 Підтримка"), KeyboardButton(text="ℹ️ Довідка")],
            ],
            resize_keyboard=True,
        )

    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛍 Каталог"), KeyboardButton(text="🛒 Кошик")],
            [KeyboardButton(text="👤 Профіль"), KeyboardButton(text="🆘 Підтримка")],
            [KeyboardButton(text="ℹ️ Довідка")],
        ],
        resize_keyboard=True,
    )


# Константа лишається для сумісності, але хендлери викликають main_menu():
# у serverless модуль імпортується один раз, а PUBLIC_URL може зʼявитись пізніше
MAIN_MENU = main_menu()


def support_mode_menu() -> ReplyKeyboardMarkup:
    """Єдина клавіша під час /ask — щоб інші дії не змішували контексти."""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="✅ Завершити звернення")]],
        resize_keyboard=True,
    )


PHONE_REQUEST = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="📱 Надіслати номер", request_contact=True)]],
    resize_keyboard=True,
    one_time_keyboard=True,
)


def age_gate() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Так, мені є 18", callback_data="age:yes"),
                InlineKeyboardButton(text="Ні", callback_data="age:no"),
            ]
        ]
    )


# ---------------------------------------------------------------------- каталог

def categories(items: list[Category]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for c in items:
        kb.button(text=c.name, callback_data=f"cat:{c.id}")
    kb.adjust(2)
    return kb.as_markup()


def products(items: list[Product], category_id: int, page: int, pages: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for p in items:
        mark = "" if p.stock > 0 else " (немає)"
        kb.button(text=f"{p.name} — {p.price:.0f} грн{mark}", callback_data=f"prod:{p.id}")
    kb.adjust(1)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="←", callback_data=f"catpage:{category_id}:{page - 1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page + 1}/{pages}", callback_data="noop"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="→", callback_data=f"catpage:{category_id}:{page + 1}"))
    if nav:
        kb.row(*nav)

    kb.row(InlineKeyboardButton(text="⬅️ До категорій", callback_data="catalog"))
    return kb.as_markup()


def product_card(product: Product, in_cart: int = 0) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if product.stock > 0:
        if in_cart:
            kb.row(
                InlineKeyboardButton(text="−", callback_data=f"cartqty:{product.id}:{in_cart - 1}"),
                InlineKeyboardButton(text=f"{in_cart} шт", callback_data="noop"),
                InlineKeyboardButton(text="+", callback_data=f"cartqty:{product.id}:{in_cart + 1}"),
            )
            kb.row(InlineKeyboardButton(text="🛒 Перейти в кошик", callback_data="cart"))
        else:
            kb.row(InlineKeyboardButton(text="🛒 Додати в кошик", callback_data=f"add:{product.id}"))
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"cat:{product.category_id}"))
    return kb.as_markup()


# ------------------------------------------------------------------------ кошик

def cart(items: list[CartItem]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for i in items:
        kb.row(InlineKeyboardButton(text=f"{i.product.name}", callback_data="noop"))
        kb.row(
            InlineKeyboardButton(text="−", callback_data=f"cartqty:{i.product_id}:{i.qty - 1}"),
            InlineKeyboardButton(text=f"{i.qty} шт", callback_data="noop"),
            InlineKeyboardButton(text="+", callback_data=f"cartqty:{i.product_id}:{i.qty + 1}"),
            InlineKeyboardButton(text="🗑", callback_data=f"cartqty:{i.product_id}:0"),
        )
    kb.row(InlineKeyboardButton(text="✅ Оформити замовлення", callback_data="checkout"))
    kb.row(
        InlineKeyboardButton(text="🛍 Каталог", callback_data="catalog"),
        InlineKeyboardButton(text="Очистити", callback_data="cartclear"),
    )
    return kb.as_markup()


# --------------------------------------------------------------------- checkout

SKIP = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="Пропустити", callback_data="skip")]]
)


def payment_methods() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Переказ на картку", callback_data="pay:card")],
            [InlineKeyboardButton(text="📦 Накладений платіж", callback_data="pay:cod")],
        ]
    )


def bonus_prompt(amount) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"Списати {amount:.0f} грн бонусів", callback_data="bonus:yes")],
            [InlineKeyboardButton(text="Не використовувати", callback_data="bonus:no")],
        ]
    )


def confirm_order() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Підтвердити", callback_data="order:confirm")],
            [InlineKeyboardButton(text="❌ Скасувати", callback_data="order:cancel")],
        ]
    )


# ---------------------------------------------------------------------- профіль

def profile(referral_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📦 Мої замовлення", callback_data="myorders")],
            [InlineKeyboardButton(
                text="🔗 Поділитися посиланням",
                url=share_link(referral_link),
            )],
        ]
    )


def admin_order(
    order_id: int,
    payment_method: str | None = None,
    status: OrderStatus | str | None = None,
) -> InlineKeyboardMarkup | None:
    """Кнопки статусів під замовленням.

    Показуємо лише переходи, дозволені *з поточного статусу*. Раніше під
    кожним замовленням постійно висіли «Прийнято / Оплачено / Відправлено /
    Виконано / Скасувати», а bot/handlers/admin.py взагалі не перевіряв
    маршрут. У живому журналі це дало неможливий ланцюжок
    ``shipped -> paid -> shipped`` за 23 секунди.

    ``status=None`` лишає сумісність зі старими викликами й означає NEW.
    Після фінального статусу клавіатури немає: старі кнопки не повинні
    дозволяти повертати виконане замовлення назад.
    """
    try:
        current_status = status if isinstance(status, OrderStatus) else OrderStatus(status or "new")
    except ValueError:
        current_status = OrderStatus.NEW

    allowed = route_for(payment_method).get(current_status, set())
    if not allowed:
        return None

    labels = {
        OrderStatus.ACCEPTED: "Прийнято",
        OrderStatus.PAID: "Оплачено",
        OrderStatus.SHIPPED: "Відправлено",
        OrderStatus.DONE: "Виконано",
        OrderStatus.CANCELLED: "Скасувати",
    }
    order = (
        OrderStatus.ACCEPTED,
        OrderStatus.PAID,
        OrderStatus.SHIPPED,
        OrderStatus.DONE,
        OrderStatus.CANCELLED,
    )
    buttons = [
        InlineKeyboardButton(
            text=labels[target], callback_data=f"ao:{order_id}:{target.value}"
        )
        for target in order if target in allowed
    ]
    return InlineKeyboardMarkup(inline_keyboard=[buttons])
