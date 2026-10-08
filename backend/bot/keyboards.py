from __future__ import annotations

from shop.formatting import money as format_money

from aiogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

from shop.links import app_link, share_link
from shop.entities import OrderStatus
from shop.services.shop_service import route_for
from shop.models import CartItem, Category, Product

# ------------------------------------------------------------------ головне меню

def to_private_chat() -> InlineKeyboardMarkup:
    """Кнопка з групи/каналу прямо в канонічний Named Mini App."""
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(
            text="🛍 Відкрити магазин", url=app_link(),
        )]]
    )


def faq_reply(with_shop: bool = True) -> InlineKeyboardMarkup:
    """Кнопки під автоматичною відповіддю.

    Магазин відкриваємо через Named Mini App, а не прямий ``/app/`` URL:
    Telegram сам створює коректний launch context з initData.
    """
    rows = []
    if with_shop:
        rows.append([InlineKeyboardButton(text="🛍 Відкрити магазин", url=app_link())])
    rows.append([InlineKeyboardButton(text="💬 Питання менеджеру", callback_data="faq:human")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def faq_support_reply(with_shop: bool = True) -> InlineKeyboardMarkup | None:
    """Кнопки під FAQ-відповіддю всередині активної підтримки.

    Кнопка «Питання менеджеру» тут зайва: клієнт уже знаходиться в /ask і
    початкове повідомлення вже бачить команда в панелі.
    """
    if not with_shop:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Відкрити магазин", url=app_link())]
    ])


def open_shop() -> InlineKeyboardMarkup:
    """Надійний вхід у магазин через Named Mini App Telegram."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛍 Відкрити магазин", url=app_link())]
    ])


def main_menu() -> ReplyKeyboardMarkup:
    """Компактне головне меню.

    Нижня кнопка лишається текстовою: ReplyKeyboard ``web_app`` у частині
    клієнтів створює нестабільний Simple WebView. Handler надсилає окрему
    URL-кнопку на канонічний Named Mini App.
    """
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🛍 Відкрити магазин")],
            [KeyboardButton(text="🆘 Підтримка"), KeyboardButton(text="ℹ️ Довідка")],
        ],
        resize_keyboard=True,
    )


# Константа лишається для сумісності; хендлери викликають main_menu().
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

def categories(items: list[Category], subcategories=()) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Усі товари", callback_data="shelf:all")
    kb.button(text="Новинки", callback_data="shelf:new")
    kb.button(text="Акції", callback_data="shelf:sale")
    for c in items:
        kb.button(text=c.name, callback_data=f"root:{c.id}")
    for c in subcategories:
        kb.button(text=c.name, callback_data=f"sub:{c.id}")
    kb.adjust(2)
    return kb.as_markup()


def products(items: list[Product], category_id, page: int, pages: int, scope=None, children=()) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    scope = scope or f"cat:{category_id}"
    for child in children:
        kb.button(text=child.name, callback_data=f"sub:{child.id}")
    for p in items:
        mark = "" if p.stock > 0 else " (немає)"
        badge = " · Новинка" if p.is_new else ""
        if p.is_sale: badge += " · Акція"
        kb.button(text=f"{p.name} — {p.price:.2f} грн{badge}{mark}", callback_data=f"prod:{p.id}")
    kb.adjust(1)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="←", callback_data=f"browse:{scope}:{page-1}"))
    if pages > 1:
        nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="noop"))
    if page < pages-1:
        nav.append(InlineKeyboardButton(text="→", callback_data=f"browse:{scope}:{page+1}"))
    if nav: kb.row(*nav)
    kb.row(InlineKeyboardButton(text="⬅️ До каталогу", callback_data="catalog"))
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
    kb.row(InlineKeyboardButton(text="⬅️ Назад", callback_data=(f"sub:{product.subcategory_id}" if product.subcategory_id else f"root:{product.category_id}" if product.category_id else "shelf:all")))
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
            [InlineKeyboardButton(text=f"Списати {format_money(amount)} грн бонусів", callback_data="bonus:yes")],
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
