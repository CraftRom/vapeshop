from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import (
    BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator,
)

from shop.entities import BroadcastStatus, OperatorRole, OrderStatus, PromoType


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------------ auth

class LoginIn(BaseModel):
    login: str
    password: str


class TokenOut(BaseModel):
    role: str = "admin"
    name: str = ""
    access_token: str
    token_type: str = "bearer"


# -------------------------------------------------------------------- каталог

class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True


class CategoryOut(ORMModel, CategoryIn):
    id: int
    products_count: int = 0


class ProductIn(BaseModel):
    category_id: int
    name: str = Field(min_length=1, max_length=255)
    sku: str | None = Field(None, min_length=3, max_length=32)
    description: str | None = None
    price: Decimal = Field(ge=0)
    old_price: Decimal | None = None
    stock: int = Field(ge=0, default=0)
    photo_url: str | None = None
    sort_order: int = 0
    is_active: bool = True


class ProductOut(ORMModel, ProductIn):
    id: int
    category_name: str | None = None
    # Сам ідентифікатор файлу назовні не потрібен: фото віддає наш проксі.
    # Клієнту достатньо знати, що воно є.
    photo_file_id: str | None = Field(None, exclude=True)

    @computed_field
    @property
    def has_photo(self) -> bool:
        return bool(self.photo_file_id or self.photo_url)


class StockIn(BaseModel):
    stock: int = Field(ge=0)


class StockDeltaIn(BaseModel):
    delta: int = Field(ge=-10000, le=10000)


# ------------------------------------------------------------------ замовлення

class OrderItemOut(ORMModel):
    # У Firestore позиції вкладені в документ замовлення й власного id не мають —
    # це був артефакт SQL, тому поле необов'язкове.
    id: int | None = None
    product_id: int | None
    name: str
    price: Decimal
    qty: int


class OrderCustomer(ORMModel):
    id: int
    tg_id: int
    username: str | None
    first_name: str | None


class OrderOut(ORMModel):
    id: int
    status: OrderStatus
    subtotal: Decimal
    discount: Decimal
    bonus_used: Decimal
    total: Decimal
    payment_method: str | None
    contact_name: str | None
    contact_phone: str | None
    delivery_city: str | None
    delivery_address: str | None
    # Спосіб доставки й коди довідника Нової пошти. Коди лежать поруч із
    # текстом, а не замість: текст лишає замовлення читабельним і через
    # рік, коли відділення закриють, а коди дають створити накладну без
    # ручного пошуку. У старих замовленнях їх немає — і не буде.
    delivery_method: str | None = None
    delivery_city_ref: str | None = None
    delivery_warehouse_ref: str | None = None
    comment: str | None
    admin_note: str | None
    tracking_number: str | None = None
    # Накладна й стан синхронізації з SalesDrive — одні й ті самі поля,
    # звідки б не прийшла зміна (панель, бот, CRM).
    waybill_ref: str | None = None
    waybill_source: str | None = None
    waybill_cost: Decimal | None = None
    crm_id: str | None = None
    crm_status_id: str | None = None
    crm_status_name: str | None = None
    crm_state: str = ""
    crm_error: str | None = None
    crm_synced_at: datetime | None = None
    crm_snapshot: dict | None = None
    crm_fetched_at: datetime | None = None
    business_state: str = "pending"
    business_state_at: datetime | None = None
    operator_id: int | None = None
    operator_name: str = ""
    created_at: datetime | None = None
    items: list[OrderItemOut] = []
    user: OrderCustomer | None = None


class OrderPatch(BaseModel):
    status: OrderStatus | None = None
    admin_note: str | None = None
    tracking_number: str | None = Field(None, max_length=64)


class SalesDriveStatusPatch(BaseModel):
    status_id: str = Field(..., min_length=1, max_length=32)
    # Старі збірки панелі ще надсилають назву. Сервер її не довіряє:
    # актуальний підпис завжди читається з довідника SalesDrive за status_id.
    status_name: str | None = Field(None, max_length=128)


class SalesDriveProductPatch(BaseModel):
    """Одна товарна позиція для документованого /api/order/update/."""

    id: str | None = Field(None, max_length=128)
    name: str | None = Field(None, max_length=255)
    cost_per_item: Decimal | None = Field(None, ge=0)
    amount: Decimal | None = Field(None, gt=0)
    description: str | None = Field(None, max_length=1000)
    discount: str | None = Field(None, max_length=64)
    sku: str | None = Field(None, max_length=128)
    commission: str | None = Field(None, max_length=64)
    stock_id: int | None = Field(None, ge=1)
    upsell: int | None = Field(None, ge=0, le=1)

    @model_validator(mode="after")
    def _has_identity(self):
        if not (str(self.id or "").strip() or str(self.name or "").strip() or str(self.sku or "").strip()):
            raise ValueError("Для товару потрібен id, name або sku")
        return self


class SalesDriveOrderPatch(BaseModel):
    """Безпечна підмножина полів SalesDrive order-update.

    Адресні поля перевізників тут відсутні навмисно: документація
    /api/order/update/ прямо забороняє змінювати місто, відділення й адресу
    Нової Пошти/Укрпошти цим endpoint.
    """

    manager_id: int | None = Field(None, ge=1)
    payment_date: str | None = Field(None, max_length=10)
    rejection_reason_id: int | None = Field(None, ge=1)
    comment: str | None = Field(None, max_length=4000)
    payment_method: str | None = Field(None, max_length=128)
    shipping_method: str | None = Field(None, max_length=128)

    l_name: str | None = Field(None, max_length=128)
    f_name: str | None = Field(None, max_length=128)
    m_name: str | None = Field(None, max_length=128)
    phone: str | None = Field(None, max_length=64)
    email: str | None = Field(None, max_length=254)
    company: str | None = Field(None, max_length=255)
    date_of_birth: str | None = Field(None, max_length=10)
    counterparty_name: str | None = Field(None, max_length=255)
    counterparty_code: str | None = Field(None, max_length=64)

    carrier: str | None = Field(None, pattern=r"^(novaposhta|ukrposhta|meest|rozetka_delivery)$")
    tracking_number: str | None = Field(None, max_length=128)

    products: list[SalesDriveProductPatch] | None = Field(None, max_length=200)
    products_mode: str | None = Field(None, pattern=r"^replace$")

    @field_validator("payment_date", "date_of_birth", mode="after")
    @classmethod
    def _date_ddmmyyyy(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return value
        import re
        if not re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", value):
            raise ValueError("Очікується дата у форматі ДД.ММ.РРРР")
        try:
            datetime.strptime(value, "%d.%m.%Y")
        except ValueError as exc:
            raise ValueError("Некоректна календарна дата") from exc
        return value

    @model_validator(mode="after")
    def _consistent(self):
        supplied = self.model_fields_set
        if ("carrier" in supplied) != ("tracking_number" in supplied):
            raise ValueError("carrier і tracking_number потрібно передавати разом")
        if self.products_mode and not self.products:
            raise ValueError("productsMode має сенс лише разом із products")
        if not supplied:
            raise ValueError("Не передано жодного поля для SalesDrive")
        return self


class OrderMessageIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)

    @field_validator("text", mode="after")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        # min_length рахує й пробіли: без цього клієнт отримав би порожню бульбашку
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Повідомлення не може бути порожнім")
        return cleaned


class OrderMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    order_id: int
    direction: str
    author: str
    text: str
    is_read: bool
    file_kind: str | None = None
    file_name: str | None = None
    created_at: datetime | None = None


class OrderMessageResult(BaseModel):
    message: OrderMessageOut
    delivered: bool
    warning: str | None = None


# -------------------------------------------------------------- підтримка

class SupportClientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tg_id: int
    username: str | None = None
    first_name: str | None = None
    phone: str | None = None
    bot_reachable: bool = True


class SupportThreadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_message_at: datetime | None = None
    closed_at: datetime | None = None
    closed_by: str | None = None
    closed_by_name: str | None = None
    close_reason: str | None = None
    unread_count: int = 0
    user: SupportClientOut | None = None


class SupportStatsOut(BaseModel):
    open: int = 0
    closed: int = 0
    total: int = 0
    clients: int = 0
    unread: int = 0


class SupportThreadPatch(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def _status(cls, value: str) -> str:
        if value != "closed":
            raise ValueError("Закриті звернення не перевідкриваються. Дозволений лише статус closed")
        return value


class SupportMessageIn(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)

    @field_validator("text", mode="after")
    @classmethod
    def _support_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Повідомлення не може бути порожнім")
        return cleaned


class SupportMessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    thread_id: int
    user_id: int
    direction: str
    author: str
    text: str
    is_read: bool
    is_automatic: bool = False
    file_kind: str | None = None
    file_name: str | None = None
    created_at: datetime | None = None


class SupportMessageResult(BaseModel):
    message: SupportMessageOut
    delivered: bool
    warning: str | None = None


# --------------------------------------------------------- сповіщення панелі

class PanelNotificationOut(BaseModel):
    id: int
    kind: str
    title: str
    body: str = ""
    href: str | None = None
    entity_id: int | None = None
    actor: str | None = None
    created_at: datetime | None = None
    read: bool = False


class PanelNotificationPollOut(BaseModel):
    items: list[PanelNotificationOut] = Field(default_factory=list)
    unread_count: int = 0
    latest_id: int = 0



# --------------------------------------------------------------------- клієнти

class CustomerOut(ORMModel):
    id: int
    tg_id: int
    username: str | None = None
    first_name: str | None = None
    phone: str | None = None
    bonus_balance: Decimal = Decimal(0)
    is_blocked: bool = False
    referral_code: str
    created_at: datetime | None = None
    last_seen_at: datetime | None = None
    orders_count: int = 0
    total_spent: Decimal = Decimal(0)
    referrals_count: int = 0
    # Чи доходять до людини повідомлення бота: у Mini App можна купити,
    # жодного разу не відкривши чат із ботом.
    bot_reachable: bool = True


class CustomerPatch(BaseModel):
    is_blocked: bool | None = None
    bonus_delta: Decimal | None = None
    bonus_reason: str = "manual"


# ------------------------------------------------------------------ промокоди

class PromoIn(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    type: PromoType = PromoType.PERCENT
    value: Decimal = Field(gt=0)
    # Дефолт саме Decimal: ціле 0 доходило до бази як int і псувало
    # серіалізацію відповіді попередженням pydantic
    min_order: Decimal = Field(ge=0, default=Decimal(0))
    max_uses: int | None = None
    per_user_limit: int = Field(ge=1, default=1)
    expires_at: datetime | None = None
    is_active: bool = True


class PromoOut(ORMModel, PromoIn):
    id: int
    used_count: int = 0
    created_at: datetime | None = None


# -------------------------------------------------------------------- розсилки

class SegmentIn(BaseModel):
    type: str = "all"
    days: int | None = None
    min_total: Decimal | None = None


class BroadcastIn(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1)
    photo_url: str | None = None
    button_text: str | None = None
    button_url: str | None = None
    segment: SegmentIn = SegmentIn()
    # Точність — година: планувальник прокидається рідше, ніж раз на хвилину,
    # і обіцяти хвилинну точність було б неправдою.
    scheduled_at: datetime | None = None


class ScheduleIn(BaseModel):
    scheduled_at: datetime


class BroadcastOut(ORMModel):
    id: int
    title: str
    text: str
    photo_url: str | None
    button_text: str | None
    button_url: str | None
    segment: dict
    status: BroadcastStatus
    sent_count: int = 0
    failed_count: int = 0
    cursor_id: int = 0
    scheduled_at: datetime | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


# ------------------------------------------------------------------ статистика

class StatsOut(BaseModel):
    revenue_total: Decimal
    revenue_period: Decimal
    sales_total: Decimal = Decimal(0)
    sales_period: Decimal = Decimal(0)
    # Deprecated aliases: дорівнюють sales_* і лишені для сумісності.
    confirmed_total: Decimal = Decimal(0)
    confirmed_period: Decimal = Decimal(0)
    shipped_total: Decimal = Decimal(0)
    shipped_period: Decimal = Decimal(0)
    expected_total: Decimal = Decimal(0)
    expected_period: Decimal = Decimal(0)
    actual_received_total: Decimal = Decimal(0)
    actual_received_period: Decimal = Decimal(0)
    calculated_received_total: Decimal = Decimal(0)
    calculated_received_period: Decimal = Decimal(0)
    orders_total: int
    orders_new: int
    customers_total: int
    customers_period: int
    active_users_period: int = 0
    active_users_24h: int = 0
    buyers_period: int = 0
    avg_check: Decimal
    avg_check_period: Decimal = Decimal(0)
    orders_period: int = 0
    sales_orders_period: int = 0
    confirmed_orders_period: int = 0
    shipped_orders_period: int = 0
    low_stock: int


class SeriesPoint(BaseModel):
    date: str
    # revenue = вже отримано; sales = оборот фактичних CRM «Продаж».
    revenue: Decimal
    sales: Decimal = Decimal(0)
    # Deprecated alias для старих клієнтів.
    confirmed: Decimal = Decimal(0)
    expected: Decimal = Decimal(0)
    orders: int
    shipped: int = 0


class TopProduct(BaseModel):
    name: str
    qty: int
    revenue: Decimal


# ----------------------------------------------------------- налаштування


# Похідні поля відповіді: панель бачить їх у GET, але записувати нема
# чого — вони обчислюються з інших. Перелічені поіменно, щоб одруківка
# й далі падала, а власна ж відповідь приймалась назад без правок.
DERIVED_FIELDS = {
    "novaposhta_connected", "salesdrive_form_connected",
    "salesdrive_api_connected", "salesdrive_webhook_connected",
}


class ShopSettingsIn(BaseModel):
    # extra="forbid": одруківка в назві поля має падати одразу, а не
    # мовчки ігноруватись. Інакше «Збережено» показується, значення не
    # зберігається, і причину шукають тижнями.
    #
    # Ціна цієї суворості: те, що API віддає в GET, має прийматись у PUT.
    # Панель показує форму й натисканням «Зберегти» шле її назад — а у
    # відповіді є ознака novaposhta_connected, якої на записі немає.
    # Одне зайве ім'я відхиляло весь запит, і зберегти не вдавалось
    # нічого. Тому похідні поля відкидаємо мовчки й поіменно.
    model_config = ConfigDict(extra="forbid")

    @field_validator("salesdrive_status_map", "salesdrive_payment_map",
                     "salesdrive_shipping_map", mode="after")
    @classmethod
    def _mapping_json(cls, value, info):
        """Відповідності — JSON-обʼєкт «наше значення → значення SalesDrive».

        Перевіряємо на вході, а не при першій синхронізації: зіпсований
        JSON, прийнятий панеллю, тихо вимкнув би передачу статусів, і про
        це дізнались би з CRM, де замовлення тижнями стоять «новими».
        """
        if value is None or not value.strip():
            return value
        from shop.services.salesdrive import validate_mapping
        problem = validate_mapping(info.field_name, value)
        if problem:
            raise ValueError(problem)
        return value

    @model_validator(mode="before")
    @classmethod
    def _drop_derived(cls, data):
        if isinstance(data, dict):
            return {k: v for k, v in data.items() if k not in DERIVED_FIELDS}
        return data

    shop_name: str | None = Field(None, min_length=1, max_length=64)
    currency: str | None = Field(None, min_length=1, max_length=16)
    min_age: int | None = Field(None, ge=18, le=99)
    referral_enabled: bool | None = None
    referral_percent: Decimal | None = Field(None, ge=0, le=100)
    bonus_enabled: bool | None = None
    bonus_max_percent: Decimal | None = Field(None, ge=0, le=100)
    volume_discount_enabled: bool | None = None
    volume_discount_min: Decimal | None = Field(None, ge=0)
    volume_discount_percent: Decimal | None = Field(None, ge=0, le=100)
    card_number: str | None = Field(None, max_length=32)
    card_holder: str | None = Field(None, max_length=64)
    seller_name: str | None = Field(None, max_length=255)
    seller_code: str | None = Field(None, max_length=32)
    seller_address: str | None = Field(None, max_length=255)
    seller_email: str | None = Field(None, max_length=128)
    seller_phone: str | None = Field(None, max_length=32)
    admin_chat_id: int | None = None
    delivery_cost_from: int | None = Field(None, ge=0, le=100000)
    delivery_days: str | None = Field(None, max_length=64)
    cod_commission_percent: Decimal | None = Field(None, ge=0, le=100)
    cod_commission_fixed: Decimal | None = Field(None, ge=0, le=10000)
    # Ключ приймається, але назад не віддається — див. ShopSettingsOut.
    # Порожній рядок — це «відключити», а не «не чіпати»: інакше
    # скомпрометований ключ неможливо було б прибрати з панелі.
    novaposhta_api_key: str | None = Field(None, max_length=128)
    novaposhta_sender_city: str | None = Field(None, max_length=128)
    novaposhta_sender_phone: str | None = Field(None, max_length=32)
    novaposhta_sender_warehouse_ref: str | None = Field(None, max_length=64)
    novaposhta_sender_warehouse: str | None = Field(None, max_length=255)
    novaposhta_cargo_description: str | None = Field(None, max_length=100)
    salesdrive_enabled: bool | None = None
    # Лише субдомен: «elfar» з elfar.salesdrive.me. Повну адресу збирає
    # код — так ключ неможливо відправити на чужий хост одруківкою.
    salesdrive_domain: str | None = Field(
        None, max_length=63, pattern=r"^$|^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    # Секрети, як і ключ Нової пошти: записуються, але не читаються.
    salesdrive_form_key: str | None = Field(None, max_length=128)
    @field_validator("salesdrive_telegram_form_id", mode="before")
    @classmethod
    def _empty_salesdrive_form_id(cls, value):
        # Порожнє поле і legacy 0 означають «ще не привʼязано». Це не має
        # ламати збереження інших налаштувань SalesDrive.
        if value in (None, "", 0, "0"):
            return None
        return value

    salesdrive_telegram_form_id: int | None = Field(None, ge=1, le=2147483647)
    salesdrive_api_key: str | None = Field(None, max_length=128)
    salesdrive_webhook_token: str | None = Field(
        None, max_length=128, pattern=r"^$|^[A-Za-z0-9_-]{24,128}$")
    salesdrive_site: str | None = Field(None, max_length=128)
    salesdrive_status_map: str | None = Field(None, max_length=2000)
    salesdrive_payment_map: str | None = Field(None, max_length=1000)
    salesdrive_shipping_map: str | None = Field(None, max_length=1000)
    delivery_courier_enabled: bool | None = None
    faq_public_enabled: bool | None = None
    faq_admin_chat_enabled: bool | None = None
    delivery_weight_per_item: Decimal | None = Field(None, gt=0, le=100)
    admin_topic_id: int | None = Field(None, ge=0)
    chat_topic_id: int | None = Field(None, ge=0)
    error_topic_id: int | None = Field(None, ge=0)
    admin_ids: str | None = Field(None, max_length=255)
    bot_username: str | None = Field(None, max_length=64)
    miniapp_short_name: str | None = Field(None, max_length=64)
    public_url: str | None = Field(None, max_length=255)
    jwt_ttl_hours: int | None = Field(None, ge=1, le=720)

    # --- розсилки ---
    timezone: str | None = Field(None, max_length=64)
    broadcast_rate_per_second: int | None = Field(None, ge=1, le=30)
    quiet_hours_enabled: bool | None = None
    quiet_hours_start: int | None = Field(None, ge=0, le=23)
    quiet_hours_end: int | None = Field(None, ge=0, le=23)
    broadcast_chunk: int | None = Field(None, ge=10, le=1000)

    # --- сервер ---
    backup_enabled: bool | None = None
    backup_hour: int | None = Field(None, ge=0, le=23)
    backup_retention_days: int | None = Field(None, ge=1, le=365)

    @field_validator("timezone", mode="after")
    @classmethod
    def _check_timezone(cls, value):
        """Незнайома зона не має доїхати до бази.

        Помилка тут — це підказка в панелі; помилка після збереження — це
        розсилка, що поїхала не в ту годину, і зрозуміти чому буде складно.
        """
        if not value:
            return value
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        value = value.strip()
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(
                f"Невідома часова зона {value!r}. Потрібна назва IANA, як-от Europe/Kyiv"
            ) from None
        return value

    @field_validator("bot_username", "miniapp_short_name", mode="after")
    @classmethod
    def _clean_name(cls, value):
        # Люди копіюють із «собакою» або зі слешем — приймаємо як є
        return value.strip().lstrip("@").strip("/") if value else value

    @field_validator("public_url", mode="after")
    @classmethod
    def _check_url(cls, value):
        if not value:
            return value
        from shop.config import canonical_public_url
        value = canonical_public_url(value)
        if not value.startswith("https://"):
            raise ValueError("Адреса має починатися з https:// — Telegram не приймає http")
        return value

    @field_validator("admin_ids", mode="after")
    @classmethod
    def _check_ids(cls, value):
        if not value:
            return value
        cleaned = []
        for chunk in value.replace(";", ",").split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            if not chunk.lstrip("-").isdigit():
                raise ValueError(f"«{chunk}» не схоже на Telegram ID — потрібні лише числа")
            cleaned.append(chunk)
        return ",".join(cleaned)


class ShopSettingsOut(BaseModel):
    shop_name: str
    currency: str
    min_age: int
    referral_enabled: bool
    referral_percent: Decimal
    bonus_enabled: bool
    bonus_max_percent: Decimal
    volume_discount_enabled: bool
    volume_discount_min: Decimal
    volume_discount_percent: Decimal
    card_number: str
    card_holder: str
    seller_name: str
    seller_code: str
    seller_address: str
    seller_email: str
    seller_phone: str
    admin_chat_id: int
    admin_topic_id: int
    chat_topic_id: int
    error_topic_id: int
    delivery_cost_from: int
    delivery_days: str
    cod_commission_percent: Decimal
    cod_commission_fixed: Decimal
    # Ознака замість значення. Ключ Нової пошти — єдине налаштування,
    # яке навмисно не читається назад: ним створюють накладні від нашого
    # імені, тож у відповіді API йому не місце. Панель показує стан
    # «підключено», а щоб замінити ключ — його вписують наново.
    novaposhta_connected: bool
    novaposhta_sender_city: str
    novaposhta_sender_phone: str
    novaposhta_sender_warehouse_ref: str
    novaposhta_sender_warehouse: str
    novaposhta_cargo_description: str
    salesdrive_enabled: bool
    salesdrive_domain: str
    salesdrive_form_connected: bool
    salesdrive_telegram_form_id: int
    salesdrive_api_connected: bool
    salesdrive_webhook_connected: bool
    salesdrive_site: str
    salesdrive_status_map: str
    salesdrive_payment_map: str
    salesdrive_shipping_map: str
    delivery_courier_enabled: bool
    faq_public_enabled: bool
    faq_admin_chat_enabled: bool
    delivery_weight_per_item: Decimal
    admin_ids: str
    bot_username: str
    miniapp_short_name: str
    public_url: str
    timezone: str
    broadcast_rate_per_second: int
    quiet_hours_enabled: bool
    quiet_hours_start: int
    quiet_hours_end: int
    broadcast_chunk: int
    backup_enabled: bool
    backup_hour: int
    backup_retention_days: int
    # Читається назад, як і решта. Поле, яке можна записати, але не можна
    # прочитати, ніхто не перевірить: форма покаже дефолт замість
    # збереженого, і людина дізнається про це найпізніше.
    jwt_ttl_hours: int


# ------------------------------------------------------------- менеджери


class OperatorCreate(BaseModel):
    login: str = Field(..., min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    name: str = Field("", max_length=128)
    password: str = Field(..., min_length=8, max_length=128)
    role: OperatorRole = OperatorRole.MANAGER

    @field_validator("role", mode="after")
    @classmethod
    def _creatable(cls, value: OperatorRole) -> OperatorRole:
        """Системного адміністратора в панелі не створюють.

        Його обліковий запис приходить із .env разом із доступом до
        сервера — створити такого через веб означало б віддати ключі від
        інфраструктури тому, хто має лише пароль від панелі.
        """
        from shop.entities import CREATABLE_ROLES

        if value not in CREATABLE_ROLES:
            raise ValueError(
                "Доступні ролі: Адміністратор і Менеджер. "
                "Системний адміністратор задається у файлі .env"
            )
        return value


class OperatorUpdate(BaseModel):
    name: str | None = Field(None, max_length=128)
    password: str | None = Field(None, min_length=8, max_length=128)
    role: OperatorRole | None = None

    @field_validator("role", mode="after")
    @classmethod
    def _creatable(cls, value):
        from shop.entities import CREATABLE_ROLES

        if value is not None and value not in CREATABLE_ROLES:
            raise ValueError(
                "Доступні ролі: Адміністратор і Менеджер. "
                "Системний адміністратор задається у файлі .env"
            )
        return value
    is_active: bool | None = None


class OperatorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: str
    name: str
    role: OperatorRole
    # Береться з властивості Operator.role_title через from_attributes:
    # один підпис на систему, а не копія в кожній схемі.
    role_title: str = ""
    is_active: bool
    created_at: datetime | None = None
    last_login_at: datetime | None = None

