"""API вітрини для Telegram Mini App.

Тонкий шар над shop_service — тією ж логікою, якою користується бот.
Кошик, промокоди й оформлення не дублюються: якщо правило зміниться,
воно зміниться одночасно для бота й для міні-застосунку.

Автентифікація — через підписаний Telegram initData, а не JWT панелі.
Кожен запит стосується лише того покупця, чий підпис прийшов у заголовку.
"""
from __future__ import annotations

import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from api.schemas import CategoryOut, ProductOut
from shop.links import app_link
from api.webapp_auth import require_webapp_user
from shop.entities import User
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services import order_chat as svc_chat
from shop.services import shop_service as svc
from shop.services.notifications import notify_new_order
from shop.services.shop_settings import get_shop_settings

log = logging.getLogger(__name__)

router = APIRouter()


# ------------------------------------------------------------------ схеми


class ShopConfigOut(BaseModel):
    shop_name: str
    currency: str
    min_age: int
    age_confirmed: bool
    # Прапорці модулів. Вимкнений модуль вітрина ховає повністю:
    # клієнт не має бачити ні нулів, ні перемикачів, які нічого не роблять.
    referral_enabled: bool
    referral_percent: Decimal
    bonus_enabled: bool
    bonus_max_percent: Decimal
    volume_discount_enabled: bool
    volume_discount_min: Decimal
    volume_discount_percent: Decimal


class CartLineOut(BaseModel):
    product_id: int
    name: str
    price: Decimal
    qty: int
    line_total: Decimal
    stock: int


class CartOut(BaseModel):
    lines: list[CartLineOut]
    subtotal: Decimal
    problems: list[str] = []


class CartChangeIn(BaseModel):
    product_id: int
    delta: int = Field(..., ge=-99, le=99)


class PromoCheckIn(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)


class PromoCheckOut(BaseModel):
    ok: bool
    discount: Decimal = Decimal(0)
    error: str | None = None


class ProfileOut(BaseModel):
    first_name: str | None
    orders_count: int
    total_spent: Decimal
    bonus_balance: Decimal
    referrals_count: int
    referral_link: str
    max_bonus_now: Decimal


class CheckoutIn(BaseModel):
    contact_surname: str | None = Field(None, max_length=64)
    contact_name: str = Field(..., min_length=1, max_length=128)
    contact_patronymic: str | None = Field(None, max_length=64)
    contact_phone: str = Field(..., min_length=5, max_length=32)
    city: str = Field(..., min_length=1, max_length=128)
    address: str = Field(..., min_length=1, max_length=255)
    payment_method: str = Field(..., pattern="^(card|cod)$")
    comment: str | None = Field(None, max_length=500)
    promo_code: str | None = Field(None, max_length=64)
    use_bonus: bool = False


class CheckoutOut(BaseModel):
    order_id: int
    total: Decimal
    payment_method: str
    card_number: str | None = None
    card_holder: str | None = None


# ------------------------------------------------------------------ вітрина


def _config(shop, user) -> ShopConfigOut:
    return ShopConfigOut(
        shop_name=shop.shop_name, currency=shop.currency, min_age=shop.min_age,
        age_confirmed=user.age_confirmed,
        referral_enabled=shop.referral_enabled,
        referral_percent=shop.referral_percent,
        bonus_enabled=shop.bonus_enabled,
        bonus_max_percent=shop.bonus_max_percent,
        volume_discount_enabled=shop.volume_discount_enabled,
        volume_discount_min=shop.volume_discount_min,
        volume_discount_percent=shop.volume_discount_percent,
    )


@router.get("/config", response_model=ShopConfigOut)
async def config(
    user: User = Depends(require_webapp_user), repo: Repository = Depends(get_repo)
):
    shop = await get_shop_settings(repo)
    return _config(shop, user)


class BootstrapOut(BaseModel):
    """Усе, що потрібно вітрині при відкритті, одним запитом."""

    config: ShopConfigOut
    cart: CartOut | None = None
    profile: ProfileOut | None = None
    categories: list[CategoryOut] = []
    products: list[ProductOut] = []
    orders: list[dict] = []


@router.get("/bootstrap", response_model=BootstrapOut)
async def bootstrap(
    user: User = Depends(require_webapp_user), repo: Repository = Depends(get_repo)
):
    """Стартові дані вітрини за один раунд-тріп.

    Раніше застосунок робив шість окремих запитів: конфіг, кошик, профіль,
    замовлення, категорії, товари. На мобільному зв'язку це шість затримок
    поспіль, а в serverless — ще й шість холодних стартів. Тепер один.

    До підтвердження віку віддаємо лише конфіг: каталог за бар'єром 18+.
    """
    shop = await get_shop_settings(repo)
    config = _config(shop, user)
    if not user.age_confirmed:
        return BootstrapOut(config=config)

    # Послідовно, а не через asyncio.gather: сесія SQLAlchemy не розрахована
    # на одночасні запити й падає з IllegalStateChangeError. Виграш і так у
    # тому, що це один HTTP-раунд замість шести, а не в паралелізмі всередині.
    cart = await _cart_payload(repo, user.id)
    profile_data = await _profile_payload(repo, shop, user)
    categories = await repo.list_categories(only_active=True)
    products = await repo.list_products(only_active=True)
    orders = await _orders_payload(repo, user.id)
    return BootstrapOut(
        config=config, cart=cart, profile=profile_data,
        categories=categories, products=products, orders=orders,
    )


@router.post("/age-confirm", response_model=ShopConfigOut)
async def age_confirm(
    user: User = Depends(require_webapp_user), repo: Repository = Depends(get_repo)
):
    """Той самий 18+ бар'єр, що й у боті — вітрина не має його обходити."""
    await repo.confirm_age(user)
    shop = await get_shop_settings(repo)
    # Перечитуємо: confirm_age оновлює запис, а обʼєкт у памʼяті може
    # лишитись зі старим прапорцем — і вітрина знову показала б бар'єр віку
    return _config(shop, await repo.get_user(user.id) or user)


def _require_age(user: User) -> None:
    if not user.age_confirmed:
        raise HTTPException(403, "Спочатку підтвердьте вік")


@router.get("/categories", response_model=list[CategoryOut])
async def categories(
    user: User = Depends(require_webapp_user), repo: Repository = Depends(get_repo)
):
    _require_age(user)
    return await repo.list_categories(only_active=True)


@router.get("/products", response_model=list[ProductOut])
async def products(
    category_id: int | None = None,
    search: str | None = None,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    _require_age(user)
    return await repo.list_products(
        category_id=category_id, search=search, only_active=True
    )


@router.get("/products/{product_id}", response_model=ProductOut)
async def product(
    product_id: int,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    """Один товар — для сторінки з повним описом."""
    _require_age(user)
    found = await repo.get_product(product_id)
    if not found or not found.is_active:
        raise HTTPException(404, "Товар не знайдено")
    return found


@router.get("/products/{product_id}/photo")
async def product_photo(
    product_id: int,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    """Фото товару, завантажене через бота.

    Пряме посилання на Telegram містить токен бота у відкритому вигляді,
    тож віддаємо файл через себе. Товари з photo_url сюди не потрапляють —
    вітрина показує таку адресу напряму.
    """
    _require_age(user)
    found = await repo.get_product(product_id)
    if not found or not found.photo_file_id:
        raise HTTPException(404, "Фото немає")

    from api.routers.orders import _bot

    bot = _bot()
    if not bot:
        raise HTTPException(503, "Бот недоступний — фото не отримати")
    try:
        info = await bot.get_file(found.photo_file_id)
        content = await bot.download_file(info.file_path)
    except Exception:
        log.warning("Не вдалося отримати фото товару %s", product_id, exc_info=True)
        raise HTTPException(502, "Telegram не віддав фото")

    data = content.read() if hasattr(content, "read") else content
    return Response(
        content=data,
        media_type="image/jpeg",
        # Фото товару змінюється рідко — хай браузер тримає його добу
        headers={"Cache-Control": "private, max-age=86400"},
    )


# ------------------------------------------------------------------ кошик


async def _cart_payload(repo: Repository, user_id: int) -> CartOut:
    lines = await repo.get_cart(user_id)
    return CartOut(
        # CartLine несе вкладений Product, а не пласкі поля
        lines=[
            CartLineOut(
                product_id=l.product_id,
                name=l.product.name if l.product else "—",
                price=l.product.price if l.product else Decimal(0),
                qty=l.qty,
                line_total=l.line_total,
                stock=l.product.stock if l.product else 0,
            )
            for l in lines
        ],
        subtotal=Decimal(sum((l.line_total for l in lines), Decimal(0))),
        problems=await svc.validate_cart(repo, user_id),
    )


@router.get("/cart", response_model=CartOut)
async def cart(
    user: User = Depends(require_webapp_user), repo: Repository = Depends(get_repo)
):
    _require_age(user)
    return await _cart_payload(repo, user.id)


@router.post("/cart", response_model=CartOut)
async def change_cart(
    data: CartChangeIn,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    _require_age(user)
    await svc.add_to_cart(repo, user.id, data.product_id, data.delta)
    return await _cart_payload(repo, user.id)


@router.delete("/cart", response_model=CartOut)
async def clear_cart(
    user: User = Depends(require_webapp_user), repo: Repository = Depends(get_repo)
):
    _require_age(user)
    await repo.clear_cart(user.id)
    return await _cart_payload(repo, user.id)


# --------------------------------------------------------- промокод, профіль


@router.post("/promo/check", response_model=PromoCheckOut)
async def promo_check(
    data: PromoCheckIn,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    _require_age(user)
    subtotal = await svc.cart_subtotal(repo, user.id)
    result = await svc.check_promo(repo, data.code, user.id, subtotal)
    return PromoCheckOut(
        ok=result.ok, discount=Decimal(result.discount), error=result.error
    )


async def _profile_payload(repo: Repository, shop, user: User) -> ProfileOut:
    """Спільне тіло профілю — щоб bootstrap і окремий ендпоінт не розійшлися."""
    fresh = await repo.get_user(user.id) or user
    subtotal = await svc.cart_subtotal(repo, user.id)
    return ProfileOut(
        first_name=fresh.first_name,
        orders_count=fresh.orders_count,
        total_spent=fresh.total_spent,
        # Вимкнений модуль не має лишати по собі ні балансу, ні посилання
        bonus_balance=fresh.bonus_balance if shop.bonus_enabled else Decimal("0"),
        max_bonus_now=(
            await svc.max_bonus_for_repo(repo, subtotal, fresh.bonus_balance)
            if shop.bonus_enabled else Decimal("0")
        ),
        referral_link=app_link(fresh.referral_code) if shop.referral_enabled else "",
        referrals_count=fresh.referrals_count if shop.referral_enabled else 0,
    )


@router.get("/profile", response_model=ProfileOut)
async def profile(
    user: User = Depends(require_webapp_user), repo: Repository = Depends(get_repo)
):
    return await _profile_payload(repo, await get_shop_settings(repo), user)


class ChatMessageOut(BaseModel):
    id: int
    direction: str
    author: str
    text: str
    file_kind: str | None = None
    file_name: str | None = None
    created_at: object | None = None


class ChatSendIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


async def _own_order(repo: Repository, user: User, order_id: int):
    order = await repo.get_order(order_id)
    if not order or order.user_id != user.id:
        raise HTTPException(404, "Замовлення не знайдено")
    return order


@router.get("/orders/{order_id}/chat", response_model=list[ChatMessageOut])
async def order_chat_log(
    order_id: int,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    _require_age(user)
    await _own_order(repo, user, order_id)
    return await repo.list_order_messages(order_id)


@router.post("/orders/{order_id}/chat", response_model=ChatMessageOut, status_code=201)
async def order_chat_send(
    order_id: int,
    data: ChatSendIn,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    """Повідомлення клієнта з вітрини.

    Дублює шлях через бота, але зручніше: тут видно всю історію саме цього
    замовлення, без плутанини між кількома одночасними.
    """
    _require_age(user)
    order = await _own_order(repo, user, order_id)

    text = data.text.strip()
    if not text:
        raise HTTPException(422, "Повідомлення не може бути порожнім")

    bot = None
    try:
        from api.routers.telegram import _instances

        bot, _ = _instances()
    except Exception:
        log.warning("Бот недоступний — команда не отримає сповіщення", exc_info=True)

    await svc_chat.save_incoming(repo, order, user, text, bot=bot)
    await repo.set_chat_order(user.id, order.id)
    messages = await repo.list_order_messages(order_id)
    return messages[-1]


async def _orders_payload(repo: Repository, user_id: int) -> list[dict]:
    orders = await repo.list_orders(user_id=user_id, limit=20)
    return [
        {
            "id": o.id, "status": o.status.value, "total": o.total,
            "created_at": o.created_at,
            "operator_name": o.operator_name,
            "tracking_number": o.tracking_number,
            "is_open": o.status in svc_chat.OPEN_STATUSES,
            "items": [{"name": i.name, "qty": i.qty, "price": i.price} for i in o.items],
        }
        for o in orders
    ]


@router.get("/orders")
async def my_orders(
    user: User = Depends(require_webapp_user), repo: Repository = Depends(get_repo)
):
    _require_age(user)
    return await _orders_payload(repo, user.id)


# ------------------------------------------------------------- оформлення


@router.post("/checkout", response_model=CheckoutOut)
async def checkout(
    data: CheckoutIn,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    _require_age(user)
    order, error = await svc.create_order(
        repo, user,
        contact_name=data.contact_name, contact_surname=data.contact_surname,
        contact_patronymic=data.contact_patronymic, contact_phone=data.contact_phone,
        city=data.city, address=data.address, payment_method=data.payment_method,
        comment=data.comment, promo_code=data.promo_code, use_bonus=data.use_bonus,
    )
    if error or not order:
        raise HTTPException(400, error or "Не вдалося створити замовлення")

    # Менеджер має побачити замовлення з вітрини так само, як із чату.
    # Помилка тут не скасовує замовлення: воно вже в базі й видиме в панелі.
    try:
        from api.routers.telegram import _instances

        bot, _ = _instances()
        await notify_new_order(bot, repo, order, user)
    except Exception:
        log.warning("Замовлення №%s створено, але сповіщення не пішло",
                    order.id, exc_info=True)

    shop = await get_shop_settings(repo)
    return CheckoutOut(
        order_id=order.id, total=order.total, payment_method=order.payment_method,
        card_number=shop.card_number if order.payment_method == "card" else None,
        card_holder=shop.card_holder if order.payment_method == "card" else None,
    )
