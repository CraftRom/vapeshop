"""Доменні об'єкти.

Раніше хендлери працювали напряму з ORM-моделями SQLAlchemy. Через це весь
код був намертво прив'язаний до SQL. Тепер репозиторії — і SQL, і Firestore —
повертають ці dataclass'и, а хендлери не знають, звідки взялися дані.

Імена полів навмисно збігаються з колонками SQL-моделей, щоб міграція
хендлерів не перетворилась на суцільне перейменування.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal


class OrderStatus(str, enum.Enum):
    NEW = "new"
    CONFIRMED = "confirmed"
    # Менеджер узяв замовлення в роботу і назвався клієнту
    ACCEPTED = "accepted"
    PAID = "paid"
    SHIPPED = "shipped"
    DONE = "done"
    CANCELLED = "cancelled"


class PromoType(str, enum.Enum):
    PERCENT = "percent"
    FIXED = "fixed"


class BroadcastStatus(str, enum.Enum):
    DRAFT = "draft"
    # Час запуску заданий, черга чекає. Окремий статус, а не «чернетка з
    # датою»: чернетку можна редагувати як завгодно, а заплановану розсилку
    # планувальник будь-якої миті може взяти в роботу.
    SCHEDULED = "scheduled"
    SENDING = "sending"
    SENT = "sent"
    FAILED = "failed"


PAID_STATUSES = (OrderStatus.PAID, OrderStatus.SHIPPED, OrderStatus.DONE)

STATUS_LABELS = {
    OrderStatus.NEW: "Нове",
    OrderStatus.CONFIRMED: "Підтверджене",
    OrderStatus.ACCEPTED: "Прийняте в роботу",
    OrderStatus.PAID: "Оплачене",
    OrderStatus.SHIPPED: "Відправлене",
    OrderStatus.DONE: "Виконане",
    OrderStatus.CANCELLED: "Скасоване",
}


@dataclass
class User:
    id: int
    tg_id: int
    referral_code: str
    username: str | None = None
    first_name: str | None = None
    phone: str | None = None
    full_name: str | None = None
    age_confirmed: bool = False
    chat_order_id: int | None = None
    is_blocked: bool = False
    referrer_id: int | None = None
    bonus_balance: Decimal = Decimal(0)
    # Денормалізовані лічильники. У SQL їх можна було б порахувати JOIN'ом,
    # але Firestore так не вміє — тому тримаємо актуальними в обох базах.
    orders_count: int = 0
    total_spent: Decimal = Decimal(0)
    referrals_count: int = 0
    created_at: datetime | None = None
    last_seen_at: datetime | None = None


@dataclass
class Category:
    id: int
    name: str
    description: str | None = None
    sort_order: int = 0
    is_active: bool = True
    products_count: int = 0


@dataclass
class Product:
    id: int
    category_id: int
    name: str
    price: Decimal
    description: str | None = None
    old_price: Decimal | None = None
    stock: int = 0
    photo_file_id: str | None = None
    photo_url: str | None = None
    sort_order: int = 0
    is_active: bool = True
    category_name: str | None = None
    # Нижній регістр назви — Firestore не вміє пошук без урахування регістру,
    # тому зберігаємо готове поле для префіксних запитів.
    name_lower: str = ""

    def __post_init__(self) -> None:
        if not self.name_lower:
            self.name_lower = self.name.lower()


@dataclass
class CartLine:
    product_id: int
    qty: int
    product: Product | None = None

    @property
    def line_total(self) -> Decimal:
        return self.product.price * self.qty if self.product else Decimal(0)


@dataclass
class OrderLine:
    name: str
    price: Decimal
    qty: int
    product_id: int | None = None
    id: int | None = None

    @property
    def line_total(self) -> Decimal:
        return self.price * self.qty


@dataclass
class Order:
    id: int
    user_id: int
    status: OrderStatus = OrderStatus.NEW
    subtotal: Decimal = Decimal(0)
    discount: Decimal = Decimal(0)
    bonus_used: Decimal = Decimal(0)
    total: Decimal = Decimal(0)
    promo_code_id: int | None = None
    promo_code: str | None = None
    payment_method: str | None = None
    receipt_file_id: str | None = None
    contact_name: str | None = None
    contact_surname: str | None = None
    contact_patronymic: str | None = None
    contact_phone: str | None = None
    delivery_city: str | None = None
    delivery_address: str | None = None
    delivery_method: str | None = None
    delivery_city_ref: str | None = None
    delivery_warehouse_ref: str | None = None
    comment: str | None = None
    admin_note: str | None = None
    tracking_number: str | None = None
    operator_id: int | None = None
    operator_name: str = ""
    referral_paid: bool = False
    created_at: datetime | None = None
    items: list[OrderLine] = field(default_factory=list)
    user: User | None = None
    # Готовий рядок для пошуку менеджером (ім'я + телефон, нижній регістр)
    search_key: str = ""


@dataclass
class Promo:
    id: int
    code: str
    type: PromoType = PromoType.PERCENT
    value: Decimal = Decimal(0)
    min_order: Decimal = Decimal(0)
    max_uses: int | None = None
    per_user_limit: int = 1
    used_count: int = 0
    expires_at: datetime | None = None
    is_active: bool = True
    created_at: datetime | None = None


@dataclass
class Broadcast:
    id: int
    title: str
    text: str
    photo_url: str | None = None
    button_text: str | None = None
    button_url: str | None = None
    segment: dict = field(default_factory=dict)
    status: BroadcastStatus = BroadcastStatus.DRAFT
    sent_count: int = 0
    failed_count: int = 0
    cursor_id: int = 0
    # Коли запустити. None — розсилка ручна.
    scheduled_at: datetime | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None


@dataclass
class Stats:
    revenue_total: Decimal = Decimal(0)
    revenue_period: Decimal = Decimal(0)
    orders_total: int = 0
    orders_new: int = 0
    customers_total: int = 0
    customers_period: int = 0
    # avg_check рахується за весь час, avg_check_period — за обраний період.
    # Різниця важлива: власник дивиться, чи росте чек, а не яким він був колись.
    avg_check: Decimal = Decimal(0)
    avg_check_period: Decimal = Decimal(0)
    orders_period: int = 0
    low_stock: int = 0


class OperatorRole(str, enum.Enum):
    """Ролі в панелі, від найширшої до найвужчої.

    Значення лишаються старими рядками: «admin» тепер означає системного
    адміністратора, «operator» — менеджера. Перейменувати їх у базі можна
    було б, але це міграція заради косметики, тоді як людині видно лише
    підписи в інтерфейсі, а вони окремо.
    """

    # Обліковий запис із .env. Єдиний, хто налаштовує інфраструктуру:
    # Telegram-групу, бота, Mini App, розсилки, тихі години, бекапи.
    # Живе поза таблицею — щоб було ким увійти в щойно розгорнуту систему.
    SYSADMIN = "admin"

    # Створюється в панелі. Керує каталогом, замовленнями, клієнтами,
    # промокодами й іншими менеджерами — але не інфраструктурою.
    ADMIN = "shop_admin"

    # Створюється в панелі. Працює із замовленнями й клієнтами.
    MANAGER = "operator"


# Підписи для інтерфейсу й повідомлень. Тримаємо поруч із самим переліком,
# щоб нова роль не з'явилася десь без назви.
ROLE_TITLES = {
    OperatorRole.SYSADMIN: "Системний адміністратор",
    OperatorRole.ADMIN: "Адміністратор",
    OperatorRole.MANAGER: "Менеджер",
}


# Ролі, які можна створити в панелі. Системного адміністратора створити
# не можна: він приходить із .env разом із доступом до сервера.
CREATABLE_ROLES = (OperatorRole.ADMIN, OperatorRole.MANAGER)


@dataclass
class Operator:
    """Обліковий запис для входу в панель.

    Адміністратор із .env існує поза цією таблицею — він потрібен, щоб
    увійти в щойно розгорнуту систему, де менеджерів ще немає.
    """

    id: int
    login: str
    name: str
    role: OperatorRole
    is_active: bool
    created_at: datetime | None = None
    last_login_at: datetime | None = None
    password_hash: str = ""

    @property
    def is_admin(self) -> bool:
        return self.role in (OperatorRole.SYSADMIN, OperatorRole.ADMIN)

    @property
    def role_title(self) -> str:
        """Назва ролі для інтерфейсу й повідомлень.

        Тут, а не в схемі API: підпис потрібен і боту, і журналу, і листам,
        а не лише панелі. Порахований в одному місці, він не розійдеться
        між екранами, коли з'явиться наступна роль.
        """
        return ROLE_TITLES.get(self.role, self.role.value)


@dataclass
class OrderMessage:
    id: int
    order_id: int
    user_id: int
    direction: str          # "out" — менеджер клієнту, "in" — клієнт менеджеру
    author: str
    text: str
    tg_message_id: int | None = None
    file_id: str | None = None
    file_kind: str | None = None
    file_name: str | None = None
    is_read: bool = False
    created_at: datetime | None = None

    @property
    def from_operator(self) -> bool:
        return self.direction == "out"


def operator_stats_rows(raw: list[tuple[str, int, Decimal]]) -> list[dict]:
    """Приводить розріз по менеджерах до єдиного вигляду для обох баз.

    Замовлення без менеджера не викидаються, а зводяться в рядок
    «Без менеджера»: інакше сума розрізу не збігалася б із загальним
    виторгом, і це виглядало б як втрачені гроші.
    """
    rows = []
    for name, orders, revenue in raw:
        if not orders:
            continue
        rows.append({
            "operator_name": name or "Без менеджера",
            "orders": orders,
            "revenue": revenue,
            "avg_check": (revenue / orders).quantize(Decimal("0.01")) if orders else Decimal(0),
        })
    rows.sort(key=lambda r: r["revenue"], reverse=True)
    return rows


@dataclass
class Wishlist:
    """Список бажаного покупця.

    Товари зберігаються масивом ідентифікаторів усередині списку, а не
    окремою таблицею звʼязків: список завжди читається цілком, а так це
    одне читання замість двох на обох базах.
    """

    id: int
    user_id: int
    name: str
    product_ids: list[int] = field(default_factory=list)
    created_at: datetime | None = None
    # Заповнюється при показі, у сховищі не зберігається
    products: list[Product] = field(default_factory=list)

    @property
    def size(self) -> int:
        return len(self.product_ids)


DEFAULT_WISHLIST_NAME = "Обране"
