from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON, BigInteger, Index, Boolean, DateTime, Enum, ForeignKey, Integer, Numeric,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

# На Postgres — JSONB, на решті (тести на SQLite) — звичайний JSON.
JsonType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class OrderStatus(str, enum.Enum):
    """УВАГА: перелік дублює shop.entities.OrderStatus.

    Дві копії існують, щоб моделі не тягнули за собою шар сутностей. Але
    розходження між ними мовчазне й дороге: колонка-перелік будується саме
    з цієї, тож забутий тут статус валить запис у Postgres помилкою типу,
    хоча решта коду про нього знає. Додаєте статус — додавайте в обидва.
    """

    NEW = "new"                # щойно оформлене
    CONFIRMED = "confirmed"    # менеджер підтвердив
    ACCEPTED = "accepted"      # оператор узяв у роботу й назвався клієнту
    PAID = "paid"              # оплата підтверджена
    SHIPPED = "shipped"        # відправлено
    DONE = "done"              # отримано, бонуси нараховані
    CANCELLED = "cancelled"


class PromoType(str, enum.Enum):
    PERCENT = "percent"
    FIXED = "fixed"


class BroadcastStatus(str, enum.Enum):
    DRAFT = "draft"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


# ---------------------------------------------------------------- користувачі

class User(Base):
    __tablename__ = "users"
    __table_args__ = (Index("ix_users_search", "search_key"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(64))
    first_name: Mapped[str | None] = mapped_column(String(128))
    phone: Mapped[str | None] = mapped_column(String(32))
    full_name: Mapped[str | None] = mapped_column(String(255))

    age_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    # Замовлення, у контексті якого клієнт зараз пише в бот. Зберігається в
    # базі, а не в FSM: у serverless стан між викликами не переживає
    chat_order_id: Mapped[int | None] = mapped_column(Integer)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)

    referral_code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    referrer_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    bonus_balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)

    # Денормалізація: у SQL це рахувалось JOIN'ом на кожен показ списку клієнтів
    # і кожну сегментацію. Тримаємо готові значення — Firestore інакше не вміє,
    # а SQL від цього лише виграє.
    orders_count: Mapped[int] = mapped_column(Integer, default=0)
    total_spent: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    referrals_count: Mapped[int] = mapped_column(Integer, default=0)
    # Готовий рядок для пошуку. Власна нормалізація замість lower() у запиті:
    # SQLite не вміє знижувати регістр кирилиці, і поведінка розходилась із Firestore.
    search_key: Mapped[str] = mapped_column(String(400), default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    referrer: Mapped[User | None] = relationship(remote_side=[id], back_populates="referrals")
    referrals: Mapped[list[User]] = relationship(back_populates="referrer")
    orders: Mapped[list[Order]] = relationship(back_populates="user")
    cart_items: Mapped[list[CartItem]] = relationship(back_populates="user", cascade="all, delete-orphan")


# ------------------------------------------------------------------- каталог

class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    products: Mapped[list[Product]] = relationship(back_populates="category")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        # Каталог завжди читається як "активні товари категорії за порядком"
        Index("ix_products_category_active", "category_id", "is_active", "sort_order"),
        Index("ix_products_name_lower", "name_lower"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    old_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    stock: Mapped[int] = mapped_column(Integer, default=0)
    photo_file_id: Mapped[str | None] = mapped_column(String(255))  # file_id з Telegram
    photo_url: Mapped[str | None] = mapped_column(String(512))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Готове поле для пошуку без урахування регістру (ILIKE не використовує індекс)
    name_lower: Mapped[str] = mapped_column(String(255), default="")

    category: Mapped[Category] = relationship(back_populates="products")


class CartItem(Base):
    __tablename__ = "cart_items"
    __table_args__ = (UniqueConstraint("user_id", "product_id", name="uq_cart_user_product"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"))
    qty: Mapped[int] = mapped_column(Integer, default=1)

    user: Mapped[User] = relationship(back_populates="cart_items")
    product: Mapped[Product] = relationship(lazy="joined")


# ---------------------------------------------------------------- замовлення

class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        # Список замовлень: фільтр за статусом + сортування за датою
        Index("ix_orders_status_created", "status", "created_at"),
        Index("ix_orders_user_created", "user_id", "created_at"),
        Index("ix_orders_search", "search_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    status: Mapped[OrderStatus] = mapped_column(Enum(OrderStatus), default=OrderStatus.NEW, index=True)

    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    discount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    bonus_used: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)

    promo_code_id: Mapped[int | None] = mapped_column(ForeignKey("promo_codes.id"))
    payment_method: Mapped[str | None] = mapped_column(String(32))   # card | cod
    receipt_file_id: Mapped[str | None] = mapped_column(String(255))

    # contact_name лишається повним ПІБ одним рядком — на нього спираються
    # пошук, сповіщення й уся наявна історія. Складові зберігаємо окремо,
    # бо служби доставки вимагають їх роздільно.
    contact_name: Mapped[str | None] = mapped_column(String(255))
    contact_surname: Mapped[str | None] = mapped_column(String(128))
    contact_patronymic: Mapped[str | None] = mapped_column(String(128))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    delivery_city: Mapped[str | None] = mapped_column(String(255))
    delivery_address: Mapped[str | None] = mapped_column(String(512))
    comment: Mapped[str | None] = mapped_column(Text)
    admin_note: Mapped[str | None] = mapped_column(Text)
    tracking_number: Mapped[str | None] = mapped_column(String(64))
    # Хто веде замовлення — показується клієнту після «Прийнято»
    operator_id: Mapped[int | None] = mapped_column(Integer)
    operator_name: Mapped[str] = mapped_column(String(128), default="")

    referral_paid: Mapped[bool] = mapped_column(Boolean, default=False)
    search_key: Mapped[str] = mapped_column(String(320), default="")   # ім'я + телефон, нижній регістр
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    user: Mapped[User] = relationship(back_populates="orders")
    items: Mapped[list[OrderItem]] = relationship(back_populates="order", cascade="all, delete-orphan", lazy="selectin")
    promo_code: Mapped[PromoCode | None] = relationship()


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"))
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    name: Mapped[str] = mapped_column(String(255))     # знімок на момент покупки
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    qty: Mapped[int] = mapped_column(Integer)

    order: Mapped[Order] = relationship(back_populates="items")


# ------------------------------------------------------------------ промокоди

class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    type: Mapped[PromoType] = mapped_column(Enum(PromoType), default=PromoType.PERCENT)
    value: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    min_order: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=0)
    max_uses: Mapped[int | None] = mapped_column(Integer)       # None = без ліміту
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PromoUsage(Base):
    __tablename__ = "promo_usages"

    id: Mapped[int] = mapped_column(primary_key=True)
    promo_id: Mapped[int] = mapped_column(ForeignKey("promo_codes.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BonusTx(Base):
    """Історія руху бонусів — щоб баланс завжди можна було перерахувати."""
    __tablename__ = "bonus_tx"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2))   # + нарахування, − списання
    reason: Mapped[str] = mapped_column(String(64))           # referral | spend | manual
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# -------------------------------------------------------------------- розсилки

class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(String(512))
    button_text: Mapped[str | None] = mapped_column(String(64))
    button_url: Mapped[str | None] = mapped_column(String(512))
    segment: Mapped[dict] = mapped_column(JsonType, default=dict)
    status: Mapped[BroadcastStatus] = mapped_column(Enum(BroadcastStatus), default=BroadcastStatus.DRAFT)
    # Скільки вже пройдено: id останнього обробленого користувача. Дозволяє
    # надсилати порціями і продовжувати з того ж місця після паузи або таймауту.
    cursor_id: Mapped[int] = mapped_column(Integer, default=0)
    sent_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)


class Operator(Base):
    """Оператори панелі. Адміністратор із .env тут не зберігається."""

    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(primary_key=True)
    login: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default="operator")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OrderMessage(Base):
    """Листування оператора з клієнтом у межах одного замовлення.

    Прив'язка саме до замовлення, а не до клієнта: у людини може бути кілька
    відкритих замовлень одночасно, і змішувати їх в одну стрічку означало б
    плутанину і для оператора, і для клієнта.
    """

    __tablename__ = "order_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # "out" — від оператора клієнту, "in" — від клієнта
    direction: Mapped[str] = mapped_column(String(4))
    author: Mapped[str] = mapped_column(String(128), default="")
    text: Mapped[str] = mapped_column(Text)
    # id повідомлення в Telegram: за ним відповідь клієнта зіставляється
    # із замовленням, коли їх у нього кілька
    tg_message_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    # Вкладення лишаємо як file_id Telegram: сам файл не зберігаємо,
    # панель тягне його через бекенд лише коли оператор відкриває стрічку
    file_id: Mapped[str | None] = mapped_column(String(255))
    file_kind: Mapped[str | None] = mapped_column(String(16))   # photo, document, video, voice
    file_name: Mapped[str | None] = mapped_column(String(255))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


Index("ix_order_messages_order_created", OrderMessage.order_id, OrderMessage.created_at)
