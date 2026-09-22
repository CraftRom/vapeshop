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

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, Response, Request, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator

from api.schemas import CategoryOut, ProductOut
from shop.links import app_link
from api.webapp_auth import require_webapp_user
from shop.entities import OrderStatus, User
from shop.repo.base import Repository
from shop.repo.factory import get_repo
from shop.services import novaposhta as np
from shop.services import order_chat as svc_chat
from shop.services import shop_service as svc
from shop.services.identity import contains_telegram_handle, safe_telegram_first_name
from shop.services.notifications import notify_cancelled_by_client, notify_new_order
from shop.services import wishlist as wl
from shop.services.shop_settings import get_shop_settings

log = logging.getLogger(__name__)

router = APIRouter()


class ClientLogIn(BaseModel):
    """Безпечний технічний запис із WebView.

    Поля навмисно жорстко обмежені: endpoint доступний навіть без initData,
    бо саме відсутність initData ми й повинні вміти діагностувати.
    """

    model_config = ConfigDict(extra="forbid")
    event: str = Field(..., min_length=1, max_length=80, pattern=r"^[a-z0-9_.-]+$")
    level: str = Field("info", pattern=r"^(info|warning|error)$")
    message: str = Field("", max_length=500)
    session_id: str = Field("", max_length=80)
    app_version: str = Field("", max_length=32)
    path: str = Field("", max_length=160)
    sdk: bool = False
    init_data: bool = False
    init_data_length: int = Field(0, ge=0, le=16384)
    init_data_source: str = Field("", max_length=32)
    telegram_version: str = Field("", max_length=24)
    platform: str = Field("", max_length=32)
    launch_params: list[str] = Field(default_factory=list, max_length=16)
    origin: str = Field("", max_length=160)
    referrer_origin: str = Field("", max_length=160)
    online: bool = True
    visibility: str = Field("", max_length=24)
    status: int | None = Field(None, ge=0, le=599)
    duration_ms: int | None = Field(None, ge=0, le=120000)
    error_name: str = Field("", max_length=80)
    details: dict[str, str | int | float | bool | None] = Field(default_factory=dict)

    @field_validator("launch_params")
    @classmethod
    def _clean_launch_params(cls, value):
        return [str(item)[:64] for item in value[:16]]

    @field_validator("details")
    @classmethod
    def _clean_details(cls, value):
        # Не дозволяємо перетворити журнал на довільне сховище.
        safe = {}
        # Порівнюємо нормалізовані імена. Раніше ``message_text`` після
        # replace("_", "") ставав ``messagetext``, але список заборонених
        # містив стару форму — поле фактично проходило. Також не дозволяємо
        # details підміняти серверні IP/UA/event/status.
        forbidden = {
            "initdata", "token", "authorization", "cookie", "password",
            "text", "messagetext", "ip", "useragent", "event", "status",
            "requestid", "clientsession",
        }
        for key, item in list((value or {}).items())[:20]:
            name = str(key)[:64]
            normalized = "".join(ch for ch in name.lower() if ch.isalnum())
            if normalized in forbidden:
                continue
            if isinstance(item, (str, int, float, bool)) or item is None:
                safe[name] = item[:250] if isinstance(item, str) else item
        return safe


@router.post("/client-log", status_code=204)
async def client_log(data: ClientLogIn, request: Request):
    """Приймає діагностику вітрини навіть коли Telegram auth не піднявся.

    Raw initData не приймається схемою взагалі. IP і User-Agent додає сервер,
    тож клієнт не може підробити найважливіший контекст розслідування.
    """
    from api.request_log import client_country, client_ip, current_request_id
    from shop.client_logging import get_logger

    # Клієнтські details ідуть першими: довірені поля сервера нижче мають
    # остаточний пріоритет і не можуть бути підмінені публічним endpoint.
    extra = {
        **data.details,
        "event": data.event,
        "clientSession": data.session_id,
        "appVersion": data.app_version,
        "path": data.path,
        "sdk": data.sdk,
        "initData": data.init_data,
        "initDataLength": data.init_data_length,
        "initDataSource": data.init_data_source,
        "telegramVersion": data.telegram_version,
        "platform": data.platform,
        "launchParams": data.launch_params,
        "origin": data.origin,
        "referrerOrigin": data.referrer_origin,
        "online": data.online,
        "visibility": data.visibility,
        "ip": client_ip(request),
        "country": client_country(request),
        "requestId": current_request_id.get(),
        "userAgent": request.headers.get("user-agent", "")[:300],
    }
    if data.status is not None:
        extra["status"] = data.status
    if data.duration_ms is not None:
        extra["durationMs"] = data.duration_ms
    if data.error_name:
        extra["errorName"] = data.error_name

    logger = get_logger()
    method = {"info": logger.info, "warning": logger.warning, "error": logger.error}[data.level]
    method(data.message or data.event, extra=extra)
    return Response(status_code=204)


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
    # Чи працює вибір відділення з довідника. Без ключа вітрина лишає
    # два вільні рядки — рівно те, що було до появи довідника.
    novaposhta_enabled: bool
    # Чи пропонувати курʼєра. Вимкнений — вітрина взагалі не показує
    # вибору способу доставки: один варіант краще подати як даність,
    # ніж як вибір із одного.
    courier_enabled: bool
    # Реквізити для юридичних документів. Порожні поля вітрина показує
    # як незаповнені — щоб недороблену оферту не можна було проґавити.
    seller: dict


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
    phone: str | None = None
    orders_count: int
    total_spent: Decimal
    bonus_balance: Decimal
    referrals_count: int
    referral_link: str
    # Чи доходять до людини повідомлення бота, і куди її відправити, якщо
    # ні: у Mini App можна купити, жодного разу не відкривши чат із ботом,
    # і тоді ні статуси, ні реквізити для оплати нікуди не приходять.
    bot_reachable: bool = True
    bot_link: str = ""
    max_bonus_now: Decimal


class CheckoutIn(BaseModel):
    # Ключ генерує Mini App один раз на відкриття checkout. Він не є
    # секретом; потрібен лише для ідемпотентності повторного POST після
    # timeout/поганого звʼязку.
    checkout_key: str | None = Field(None, min_length=12, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    contact_surname: str = Field(..., min_length=1, max_length=64)
    contact_name: str = Field(..., min_length=1, max_length=128)
    contact_patronymic: str | None = Field(None, max_length=64)
    contact_phone: str = Field(..., min_length=5, max_length=32)
    city: str = Field(..., min_length=1, max_length=128)
    address: str = Field(..., min_length=1, max_length=255)
    # Спосіб доставки й коди довідника. Необовʼязкові: якщо довідник
    # недоступний або ключа немає, вітрина шле самі лише текстові поля —
    # і замовлення все одно приймається.
    delivery_method: str | None = Field(None, pattern="^(warehouse|courier)$")
    delivery_city_ref: str | None = Field(None, max_length=64)
    delivery_warehouse_ref: str | None = Field(None, max_length=64)
    payment_method: str = Field(..., pattern="^(card|cod)$")
    comment: str | None = Field(None, max_length=500)
    promo_code: str | None = Field(None, max_length=64)
    use_bonus: bool = False

    @field_validator("contact_surname", "contact_name", "city", "address")
    @classmethod
    def _required_checkout_text(cls, value: str) -> str:
        """Обовʼязкові поля не можуть складатися лише з пробілів.

        Frontend робить ту саму перевірку для швидкого UX, але API не має
        довіряти клієнту: Mini App можна викликати напряму або старою версією.
        Повертаємо вже обрізане значення, щоб у CRM не накопичувався зайвий
        whitespace у ПІБ, місті та адресі.
        """
        clean = str(value or "").strip()
        if not clean:
            raise ValueError("Поле обовʼязкове")
        return clean

    @field_validator("contact_surname", "contact_name", "contact_patronymic")
    @classmethod
    def _contact_person_name_has_no_handle(cls, value: str | None):
        if value is None:
            return None
        clean = str(value or "").strip()
        if contains_telegram_handle(clean):
            raise ValueError("У ПІБ вкажіть імʼя, а не Telegram username")
        return clean

    @field_validator("contact_phone")
    @classmethod
    def _normalize_checkout_phone(cls, value: str) -> str:
        """Український номер у канонічному +380XXXXXXXXX.

        Frontend нормалізує для UX, але API не довіряє клієнту: старий
        Mini App або прямий запит інакше записував довільні 5 символів,
        після чого CRM/Нова пошта отримували недійсний номер.
        """
        digits = "".join(ch for ch in str(value or "") if ch.isdigit())
        if digits.startswith("380"):
            body = digits[3:]
        elif digits.startswith("80") and len(digits) == 11:
            body = digits[2:]
        elif digits.startswith("0") and len(digits) == 10:
            body = digits[1:]
        else:
            body = digits
        if len(body) != 9 or not body or body[0] not in "3456789":
            raise ValueError("Вкажіть коректний український номер телефону")
        return "+380" + body


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
        novaposhta_enabled=shop.novaposhta_connected,
        courier_enabled=shop.delivery_courier_enabled,
        seller={
            "SELLER_NAME": shop.seller_name,
            "SELLER_CODE": shop.seller_code,
            "SELLER_ADDRESS": shop.seller_address,
            "SELLER_EMAIL": shop.seller_email,
            "SELLER_PHONE": shop.seller_phone,
            "MIN_AGE": str(shop.min_age),
            "CURRENCY": shop.currency,
        },
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
    wishlists: list[WishlistOut] = []


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
    lists = await wl.hydrate(repo, await wl.ensure_lists(repo, user.id))
    return BootstrapOut(
        config=config, cart=cart, profile=profile_data,
        categories=categories, products=products, orders=orders,
        wishlists=[_wl_out(x) for x in lists],
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
    try:
        await svc.add_to_cart(repo, user.id, data.product_id, data.delta)
        return await _cart_payload(repo, user.id)
    except Exception:
        # Storefront telemetry показала серію POST /cart 500 у старій 2.15.0.
        # PostgreSQL row-lock race вже виправлений у repository; цей event
        # гарантує, що будь-яка інша майбутня причина матиме server traceback,
        # а не лише клієнтське «Помилка 500».
        log.exception(
            "Помилка зміни кошика користувача %s, товар %s, delta %s",
            user.id, data.product_id, data.delta,
            extra={"event": "shop.cart.change_failed", "userId": user.id,
                   "productId": data.product_id, "delta": data.delta},
        )
        raise


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
        first_name=safe_telegram_first_name(fresh.first_name, fresh.username),
        phone=fresh.phone,
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
        # Чи доходять до людини повідомлення бота. False — вітрина
        # покаже, що статуси й реквізити їй нікуди слати, і дасть
        # посилання, яким це виправити за один дотик.
        bot_reachable=fresh.bot_reachable,
        bot_link=f"https://t.me/{shop.bot_username}" if shop.bot_username else "",
    )


@router.get("/profile", response_model=ProfileOut)
async def profile(
    response: Response,
    user: User = Depends(require_webapp_user), repo: Repository = Depends(get_repo)
):
    # Профіль живий: телефон може змінитися окремим Telegram update між
    # двома GET. Не дозволяємо WebView/CDN повертати старий phone=None.
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return await _profile_payload(repo, await get_shop_settings(repo), user)


class ContactPhoneOut(BaseModel):
    phone: str | None = None


@router.get("/contact-phone", response_model=ContactPhoneOut)
async def contact_phone(
    response: Response,
    user: User = Depends(require_webapp_user), repo: Repository = Depends(get_repo),
):
    """Легке опитування після Telegram.WebApp.requestContact().

    Контакт приходить окремим Telegram update і може бути записаний іншою
    сесією/процесом уже ПІСЛЯ того, як поточний WebApp-запит авторизував
    користувача. Тому перечитуємо рядок із БД прямо тут, а не довіряємо
    об'єкту dependency. Відповідь ніколи не кешується.
    """
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    fresh = await repo.get_user(user.id) or user
    return ContactPhoneOut(phone=fresh.phone)


# ------------------------------------------------------- списки бажаного


class WishlistOut(BaseModel):
    id: int
    name: str
    size: int
    product_ids: list[int]
    products: list[ProductOut] = []


class WishlistIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)

    @field_validator("name", mode="after")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        # min_length рахує й пробіли: інакше зʼявився б список без назви
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Назва списку не може бути порожньою")
        return cleaned


class WishlistItemIn(BaseModel):
    product_id: int


def _wl_out(wl) -> WishlistOut:
    return WishlistOut(
        id=wl.id, name=wl.name, size=wl.size, product_ids=wl.product_ids,
        products=[ProductOut.model_validate(p) for p in wl.products],
    )


@router.get("/wishlists", response_model=list[WishlistOut])
async def wishlists(
    user: User = Depends(require_webapp_user), repo: Repository = Depends(get_repo)
):
    _require_age(user)
    lists = await wl.hydrate(repo, await wl.ensure_lists(repo, user.id))
    return [_wl_out(x) for x in lists]


@router.post("/wishlists", response_model=WishlistOut, status_code=201)
async def create_wishlist(
    data: WishlistIn,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    _require_age(user)
    try:
        return _wl_out(await wl.create(repo, user.id, data.name))
    except wl.WishlistError as exc:
        raise HTTPException(409, str(exc))


@router.put("/wishlists/{wishlist_id}", response_model=WishlistOut)
async def rename_wishlist(
    wishlist_id: int,
    data: WishlistIn,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    _require_age(user)
    try:
        await wl.owned(repo, wishlist_id, user.id)
    except wl.WishlistError as exc:
        raise HTTPException(404, str(exc))
    return _wl_out(await repo.rename_wishlist(wishlist_id, data.name.strip()))


@router.delete("/wishlists/{wishlist_id}", status_code=204)
async def delete_wishlist(
    wishlist_id: int,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    _require_age(user)
    try:
        await wl.drop(repo, wishlist_id, user.id)
    except wl.WishlistError as exc:
        raise HTTPException(404, str(exc))


@router.post("/wishlists/{wishlist_id}/items", response_model=WishlistOut)
async def toggle_wishlist_item(
    wishlist_id: int,
    data: WishlistItemIn,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    """Додає товар або прибирає його, якщо він уже в списку."""
    _require_age(user)
    try:
        updated, _ = await wl.toggle(repo, wishlist_id, user.id, data.product_id)
    except wl.WishlistNotFound as exc:
        raise HTTPException(404, str(exc))
    except wl.WishlistError as exc:
        raise HTTPException(409, str(exc))
    return _wl_out((await wl.hydrate(repo, [updated]))[0])


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
    after_id: int | None = Query(None, ge=0),
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    _require_age(user)
    await _own_order(repo, user, order_id)
    messages = await repo.list_order_messages(order_id, after_id=after_id)
    # Читаємо стрічку — отже, повідомлення менеджера побачені. Позначаємо
    # після вибірки, щоб у цій же відповіді клієнт не побачив «прочитано»
    # на тому, що йому щойно віддали: квитанція призначена менеджеру.
    if messages:
        await repo.mark_client_read(order_id)
    return messages


# Скріншот квитанції — те, чого просить текст після оформлення.
#
# Раніше вітрина обіцяла «надішліть скріншот у цей чат», а надіслати його
# з неї було нічим: вкладення вміла приймати лише розмова з ботом. Людина
# або шукала бота вручну, або писала «оплатив» словами, і менеджер звіряв
# оплату наосліп.
PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}
PHOTO_LIMIT = 8 * 1024 * 1024


def _photo_mime(blob: bytes) -> str | None:
    """Визначає підтримуване фото за сигнатурою, а не Content-Type клієнта."""
    if blob.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if blob.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if len(blob) >= 12 and blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "image/webp"
    return None


@router.get("/orders/{order_id}/chat/{message_id}/file")
async def order_chat_file(
    order_id: int,
    message_id: int,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    """Вкладення зі стрічки — покупцеві його ж замовлення.

    Дзеркальне до точки в панелі, але з перевіркою власника: у панель
    ходить менеджер, сюди — людина, і чужий номер замовлення тут має
    впиратись у 404, а не віддавати чиюсь квитанцію.

    Файл у нас не лежить — тягнемо його з Telegram на льоту. Прямим
    посиланням віддати не можна: адреса файлу в Telegram містить токен
    бота у відкритому вигляді.
    """
    _require_age(user)
    await _own_order(repo, user, order_id)

    messages = await repo.list_order_messages(order_id)
    target = next((m for m in messages if m.id == message_id), None)
    if not target:
        raise HTTPException(404, "Вкладення не знайдено")
    if not target.file_id:
        # Файл був, але його вже прибрали за строком зберігання. Це не
        # помилка й не втрата: так і задумано, тому й код інший.
        raise HTTPException(410, "Вкладення видалене за строком зберігання")

    bot = None
    try:
        from api.routers.telegram import _instances

        bot, _ = _instances()
    except Exception:
        log.warning("Бот недоступний — вкладення не віддати", exc_info=True)
    if not bot:
        raise HTTPException(503, "Бот недоступний — файл не отримати")

    try:
        info = await bot.get_file(target.file_id)
        content = await bot.download_file(info.file_path)
    except Exception:
        log.warning("Не вдалося отримати файл %s", target.file_id, exc_info=True)
        raise HTTPException(502, "Telegram не віддав файл")

    media = {"photo": "image/jpeg", "video": "video/mp4", "voice": "audio/ogg"}
    return Response(
        content=content.read(),
        media_type=media.get(target.file_kind, "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.post("/orders/{order_id}/chat/photo", status_code=201)
async def order_chat_photo(
    order_id: int,
    file: UploadFile = File(...),
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    """Фото у стрічку замовлення: квитанція, фото товару, скарга."""
    _require_age(user)
    order = await _own_order(repo, user, order_id)

    if file.content_type not in PHOTO_TYPES:
        raise HTTPException(422, "Підійде знімок екрана або фото: JPEG, PNG або WebP")

    # Читаємо з межею: без неї один запит із відео на сотні мегабайт
    # займе памʼять процесу, який обслуговує всіх інших.
    blob = await file.read(PHOTO_LIMIT + 1)
    if len(blob) > PHOTO_LIMIT:
        raise HTTPException(413, "Файл завеликий — до 8 МБ")
    if not blob:
        raise HTTPException(422, "Порожній файл")
    actual_mime = _photo_mime(blob)
    if actual_mime not in PHOTO_TYPES:
        raise HTTPException(422, "Файл не є підтримуваним фото JPEG, PNG або WebP")

    bot = None
    try:
        from api.routers.telegram import _instances

        bot, _ = _instances()
    except Exception:
        log.warning("Бот недоступний — фото не дійде в чат команди", exc_info=True)

    if bot is None:
        raise HTTPException(503, "Бот тимчасово недоступний — фото не збережено")

    from aiogram.types import BufferedInputFile
    from shop.services.shop_settings import get_shop_settings
    from shop.services.notifications import topic_kwargs

    shop = await get_shop_settings(repo)
    if not shop.admin_chat_id:
        raise HTTPException(503, "Чат команди не налаштований — фото не збережено")
    try:
        sent = await bot.send_photo(
            shop.admin_chat_id,
            BufferedInputFile(blob, filename=file.filename or "screenshot.jpg"),
            caption=f"📎 Вкладення до замовлення №{order.id}",
            **topic_kwargs(shop.chat_topic_id or shop.admin_topic_id),
        )
    except Exception as exc:
        log.warning("Не вдалося переслати фото в чат команди", exc_info=True)
        raise HTTPException(502, "Telegram не прийняв фото — спробуйте ще раз") from exc

    file_id = sent.photo[-1].file_id if sent.photo else None
    if not file_id:
        raise HTTPException(502, "Telegram не повернув ідентифікатор фото")
    # Зберігаємо file_id, а не сам файл: у Telegram він уже лежить, і панель
    # тягне його звідти, коли менеджер відкриває стрічку.
    attachment = {
        "file_id": file_id, "file_kind": "photo",
        "file_name": (file.filename or "screenshot.jpg")[:255],
    }
    await svc_chat.save_incoming(
        repo, order, user, "Надіслав вкладення", bot=None, attachment=attachment,
    )
    await repo.set_chat_order(user.id, order.id)
    return {"messages": await repo.list_order_messages(order_id)}


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
            # Правило скасування живе на сервері, а вітрина лише показує
            # кнопку. Дві копії умови розійшлись би при першій же зміні
            # маршруту статусів.
            "can_cancel": o.status in SELF_CANCELLABLE,
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


# Статуси, з яких покупець скасовує сам.
#
# Далі — ні. Оплачене замовлення означає, що гроші вже в нас і їх треба
# повертати; відправлене — що посилка вже їде, і скасування коштує
# зворотної пересилки. Обидва випадки вимагають людини, а не кнопки,
# тож із них ведемо в чат замовлення.
SELF_CANCELLABLE = {OrderStatus.NEW, OrderStatus.ACCEPTED}


@router.post("/orders/{order_id}/cancel")
async def cancel_my_order(
    order_id: int,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    """Скасування замовлення покупцем.

    Дає ту саму дію, що й менеджер у панелі: залишки повертаються на
    склад, списані бонуси — на рахунок. Без цієї кнопки людина писала в
    чат «скасуйте, будь ласка» і чекала, а товар усі ці години лишався
    зарезервованим за нею.
    """
    _require_age(user)
    order = await repo.get_order(order_id)
    # Чуже замовлення — 404, а не 403: підтверджувати існування чужого
    # номера немає потреби, а перебором номерів так нічого не дізнатись.
    if not order or order.user_id != user.id:
        raise HTTPException(404, "Замовлення не знайдено")

    if order.status == OrderStatus.CANCELLED:
        # Повторне натискання не помилка: людина могла не побачити
        # результату першого. Відповідаємо тим самим, що й тоді.
        return {"orders": await _orders_payload(repo, user.id)}

    if order.status not in SELF_CANCELLABLE:
        raise HTTPException(
            409,
            "Це замовлення вже в роботі — скасувати його самостійно не вийде. "
            "Напишіть у чат замовлення, і менеджер усе владнає.",
        )

    try:
        await svc.change_order_status(repo, order, OrderStatus.CANCELLED)
    except svc.OrderStateConflict as exc:
        fresh = await repo.get_order(order_id)
        if fresh and fresh.status == OrderStatus.CANCELLED:
            return {"orders": await _orders_payload(repo, user.id)}
        raise HTTPException(409, str(exc)) from exc
    await _tell_managers_cancelled(repo, order, user)
    return {"orders": await _orders_payload(repo, user.id)}


async def _tell_managers_cancelled(repo: Repository, order, user: User) -> None:
    """Повідомляє менеджерів у чат замовлення.

    Без цього скасування було б видно лише в списку — а менеджер, який
    уже пакує посилку, у список не дивиться.
    """
    bot = None
    try:
        from api.routers.telegram import _instances

        bot, _ = _instances()
    except Exception:
        # exc_info обовʼязково: мовчазний except тут означав би, що
        # сповіщення тихо не працює, і дізнаємось ми про це від клієнта,
        # якому привезли скасовану посилку.
        log.warning("Бот недоступний — про скасування не сповістимо", exc_info=True)

    try:
        await notify_cancelled_by_client(bot, repo, order, user)
    except Exception:
        # Скасування вже відбулось і відкотити його не можна. Впасти тут
        # означало б показати покупцеві помилку на успішній дії.
        log.warning("Не вдалось сповістити про скасування №%s", order.id, exc_info=True)


# --------------------------------------------------------------- доставка


async def _novaposhta_key(repo: Repository) -> str:
    shop = await get_shop_settings(repo)
    key = (shop.novaposhta_api_key or "").strip()
    if not key:
        # 503, а не 500: це не поломка, а незавершене налаштування.
        # Вітрина за цим кодом мовчки повертається до ручного вводу.
        raise HTTPException(503, "Довідник Нової пошти не підключений")
    return key


@router.get("/delivery/cities")
async def delivery_cities(
    q: str = "",
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    """Населені пункти за початком назви.

    Запит іде через наш сервер, а не з браузера: ключ приватний, ним
    створюють накладні від нашого імені.
    """
    _require_age(user)
    key = await _novaposhta_key(repo)
    try:
        found = await np.search_settlements(key, q)
    except np.NovaPoshtaError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"items": [
        {"ref": s.ref, "settlement_ref": s.settlement_ref, "name": s.name,
         "area": s.area, "label": s.label, "warehouses": s.warehouses}
        for s in found
    ]}


@router.get("/delivery/warehouses")
async def delivery_warehouses(
    city_ref: str = "", settlement_ref: str = "", q: str = "",
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    """Відділення й поштомати обраного населеного пункту."""
    _require_age(user)
    key = await _novaposhta_key(repo)
    try:
        found = await np.warehouses(key, city_ref, settlement_ref, q)
    except np.NovaPoshtaError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {"items": [
        {"ref": w.ref, "number": w.number, "label": w.label,
         "short": w.short, "is_postomat": w.is_postomat}
        for w in found
    ]}


@router.get("/delivery/price")
async def delivery_price(
    city_ref: str = "", settlement_ref: str = "", method: str = "warehouse",
    payment_method: str = "card",
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    """Попередній розрахунок доставки.

    Саме попередній. Перевізник рахує за фактичною вагою й габаритами, а
    їх ніхто не знає, поки посилку не зважать. Ми підставляємо припущену
    вагу з налаштувань — тож віддаємо орієнтир і поле approximate, яке
    вітрина зобовʼязана показати словами.

    Сума замовлення береться з кошика на сервері, а не з запиту: інакше
    її можна було б підмінити й отримати чужий розрахунок страхування.
    """
    _require_age(user)
    shop = await get_shop_settings(repo)
    lines = await repo.get_cart(user.id)
    subtotal = sum((line.line_total for line in lines), Decimal(0))
    quantity = sum(line.qty for line in lines) or 1
    # Вагу округляємо тут, один раз. Раніше в кеш ішло одне число, а
    # перевізникові — інше, округлене, і той самий кошик міг питатися
    # двічі поспіль.
    weight = round(max(float(shop.delivery_weight_per_item) * quantity, 0.1), 2)

    # Порожній кошик — рахувати нема чого. Трапляється, якщо екран
    # оформлення лишили відкритим, а товар тим часом прибрали.
    if not lines:
        return {"approximate": True, "cost": None, "redelivery": 0,
                "weight": 0, "source": "settings",
                "cost_from": float(shop.delivery_cost_from or 0)}

    fallback = {
        "approximate": True,
        "cost": None,
        "redelivery": 0,
        "weight": round(weight, 2),
        "source": "settings",
        "cost_from": float(shop.delivery_cost_from or 0),
    }

    # Скільки покупець віддасть на відділенні: сума товарів мінус знижка
    # за обсяг. Промокод і бонуси тут не враховуємо — вони застосовуються
    # при оформленні, а цей розрахунок робиться до нього.
    payable = subtotal
    if shop.volume_discount_enabled and subtotal >= shop.volume_discount_min:
        payable = subtotal - (
            subtotal * Decimal(shop.volume_discount_percent) / Decimal(100)
        ).quantize(Decimal("0.01"))

    key = (shop.novaposhta_api_key or "").strip()
    sender = (shop.novaposhta_sender_city or "").strip()
    # Немає ключа або міста відправлення — це не помилка, а незавершене
    # налаштування. Віддаємо «від» із налаштувань: приблизне число краще
    # за порожнє місце, а покупець однаково побачить, що воно приблизне.
    if not key or not sender or not (city_ref or settlement_ref):
        return fallback

    try:
        sender_ref = await np.city_ref_by_name(key, sender)
        if not sender_ref:
            return fallback
        price = await np.document_price(
            key, sender_ref, city_ref or settlement_ref,
            to_door=method == "courier" and shop.delivery_courier_enabled,
            # Оголошена вартість — сума товарів: страхування рахують від
            # неї, і знижка на неї не впливає, бо везуть саме товар.
            declared=float(subtotal),
            weight=weight,
            # А комісія за переказ — від того, що покупець реально
            # віддасть на відділенні. Раніше сюди йшла сума до знижки, і
            # комісія виходила більшою, ніж буде насправді: людина бачила
            # завищене число й відмовлялась від накладеного платежу.
            cash_on_delivery=float(payable) if payment_method == "cod" else 0,
        )
    except np.NovaPoshtaError as exc:
        # Розрахунок — не та річ, заради якої варто ламати оформлення.
        log.info("novaposhta.price unavailable: %s", exc)
        return fallback

    return {
        "approximate": True,
        "cost": price.cost,
        "redelivery": price.redelivery,
        "weight": price.weight,
        "source": "novaposhta",
        "cost_from": float(shop.delivery_cost_from or 0),
    }


# ------------------------------------------------------------- оформлення


@router.post("/checkout", response_model=CheckoutOut)
async def checkout(
    data: CheckoutIn,
    user: User = Depends(require_webapp_user),
    repo: Repository = Depends(get_repo),
):
    _require_age(user)

    # Повтор після timeout не має створювати друге замовлення. Перевіряємо
    # ключ до читання кошика: перший успішний checkout уже очистив кошик,
    # але повтор усе одно повинен повернути той самий order_id, а не 400.
    if data.checkout_key:
        existing = await repo.get_order_by_checkout_key(data.checkout_key)
        if existing:
            if existing.user_id != user.id:
                # Ключ не секретний, але повторно використати чужий не можна:
                # інакше unique index дав би внутрішню помилку замість чіткого
                # конфлікту клієнтського запиту.
                raise HTTPException(409, "Ключ оформлення вже використано")
            return CheckoutOut(
                order_id=existing.id, total=existing.total,
                payment_method=existing.payment_method or data.payment_method,
                card_number=None, card_holder=None,
            )

    shop_now = await get_shop_settings(repo)
    if data.delivery_method == "courier" and not shop_now.delivery_courier_enabled:
        # Вітрина такого не покаже, але запит міг лишитись у відкритій
        # вкладці з часів, коли курʼєр був увімкнений. Мовчки підмінити
        # спосіб не можна: адресу вписано вулицею, а не відділенням.
        raise HTTPException(
            422, "Доставка курʼєром зараз недоступна — оберіть відділення",
        )

    order, error = await svc.create_order(
        repo, user,
        contact_name=data.contact_name, contact_surname=data.contact_surname,
        contact_patronymic=data.contact_patronymic, contact_phone=data.contact_phone,
        city=data.city, address=data.address, payment_method=data.payment_method,
        delivery_method=data.delivery_method,
        delivery_city_ref=data.delivery_city_ref,
        delivery_warehouse_ref=data.delivery_warehouse_ref,
        comment=data.comment, promo_code=data.promo_code, use_bonus=data.use_bonus,
        checkout_key=data.checkout_key,
    )
    if error or not order:
        raise HTTPException(400, error or "Не вдалося створити замовлення")

    # При одночасному double-submit unique checkout_key повертає той самий
    # Order другому запиту. Бізнес-дані ідемпотентні, але Telegram/panel
    # сповіщення — ні: без цієї перевірки менеджер отримував два однакових
    # повідомлення про одне замовлення.
    replayed = bool(getattr(order, "checkout_replayed", False))

    # Отримуємо bot один раз, але не покладаємось на присвоєння всередині
    # іншого try: якщо _instances() впаде, наступний блок не повинен ловити
    # UnboundLocalError замість реальної причини недоступності Telegram.
    bot = None
    if not replayed:
        try:
            from api.routers.telegram import _instances
            bot, _ = _instances()
        except Exception:
            log.warning("Замовлення №%s створено, але Telegram bot недоступний",
                        order.id, exc_info=True)

    # Менеджер має побачити замовлення з вітрини так само, як із чату.
    # Помилка тут не скасовує замовлення: воно вже в базі й видиме в панелі.
    if not replayed:
        try:
            await notify_new_order(bot, repo, order, user)
        except Exception:
            log.warning("Замовлення №%s створено, але сповіщення не пішло",
                        order.id, exc_info=True)

    shop = await get_shop_settings(repo)

    # Підтвердження самому покупцеві. Досі його не було зовсім: вітрина
    # показувала реквізити у спливному вікні Telegram і обіцяла, що
    # «деталі надійдуть у чат», а не надходило нічого. Номер картки з
    # такого вікна не скопіювати — його доводилось переписувати з екрана
    # по пам'яті або не платити взагалі.
    #
    # У чаті картка йде тегом <code>: Telegram копіює такий текст одним
    # дотиком. Те саме, що вже роблять замовлення, оформлені в боті.
    if not replayed:
        try:
            from bot import texts

            confirmation = texts.ORDER_DONE.format(
                id=order.id, total=f"{order.total:.0f}", currency=shop.currency,
            )
            if order.payment_method == "card":
                confirmation += "\n\n" + texts.PAYMENT_INFO.format(
                    total=f"{order.total:.0f}", currency=shop.currency,
                )

            if user.bot_reachable is False:
                log.info(
                    "Підтвердження №%s не надсилається: чат клієнта недоступний",
                    order.id,
                    extra={"event": "order.confirmation.skipped_unreachable",
                           "orderId": order.id, "clientId": user.tg_id},
                )
            elif bot is None:
                raise RuntimeError("Telegram bot недоступний")
            else:
                await bot.send_message(user.tg_id, confirmation)
                await repo.set_bot_reachable(user.tg_id, True)
        except Exception as exc:
            # Замовлення вже прийнято, і провал сповіщення його не скасовує.
            # Але покупець лишився без реквізитів, тож це попередження, а не
            # мовчазний пропуск.
            from shop.services.status_messages import is_permanent_delivery_error

            if is_permanent_delivery_error(exc):
                await repo.set_bot_reachable(user.tg_id, False)
            log.warning("Замовлення №%s: покупець не отримав підтвердження",
                        order.id,
                        extra={"event": "order.confirmation.failed",
                               "orderId": order.id, "clientId": user.tg_id,
                               "permanent": is_permanent_delivery_error(exc)},
                        exc_info=True)
    return CheckoutOut(
        order_id=order.id, total=order.total, payment_method=order.payment_method,
        # Реквізити вітрині більше не віддаються: їх надсилає менеджер у
        # чат замовлення, під конкретну суму й актуальну картку.
        card_number=None, card_holder=None,
    )
