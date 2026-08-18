from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from shop.models import BroadcastStatus, OrderStatus, PromoType


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------------ auth

class LoginIn(BaseModel):
    login: str
    password: str


class TokenOut(BaseModel):
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


class StockIn(BaseModel):
    stock: int = Field(ge=0)


# ------------------------------------------------------------------ замовлення

class OrderItemOut(ORMModel):
    id: int
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
    comment: str | None
    admin_note: str | None
    created_at: datetime
    items: list[OrderItemOut] = []
    user: OrderCustomer | None = None


class OrderPatch(BaseModel):
    status: OrderStatus | None = None
    admin_note: str | None = None


# --------------------------------------------------------------------- клієнти

class CustomerOut(ORMModel):
    id: int
    tg_id: int
    username: str | None
    first_name: str | None
    phone: str | None
    bonus_balance: Decimal
    is_blocked: bool
    referral_code: str
    created_at: datetime
    last_seen_at: datetime
    orders_count: int = 0
    total_spent: Decimal = Decimal(0)


class CustomerPatch(BaseModel):
    is_blocked: bool | None = None
    bonus_delta: Decimal | None = None
    bonus_reason: str = "manual"


# ------------------------------------------------------------------ промокоди

class PromoIn(BaseModel):
    code: str = Field(min_length=2, max_length=32)
    type: PromoType = PromoType.PERCENT
    value: Decimal = Field(gt=0)
    min_order: Decimal = Field(ge=0, default=0)
    max_uses: int | None = None
    per_user_limit: int = Field(ge=1, default=1)
    expires_at: datetime | None = None
    is_active: bool = True


class PromoOut(ORMModel, PromoIn):
    id: int
    used_count: int
    created_at: datetime


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


class BroadcastOut(ORMModel):
    id: int
    title: str
    text: str
    photo_url: str | None
    button_text: str | None
    button_url: str | None
    segment: dict
    status: BroadcastStatus
    sent_count: int
    failed_count: int
    created_at: datetime
    finished_at: datetime | None


# ------------------------------------------------------------------ статистика

class StatsOut(BaseModel):
    revenue_total: Decimal
    revenue_period: Decimal
    orders_total: int
    orders_new: int
    customers_total: int
    customers_period: int
    avg_check: Decimal
    low_stock: int


class SeriesPoint(BaseModel):
    date: str
    revenue: Decimal
    orders: int


class TopProduct(BaseModel):
    name: str
    qty: int
    revenue: Decimal
