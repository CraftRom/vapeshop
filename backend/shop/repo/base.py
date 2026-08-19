"""Контракт доступу до даних.

Обидві реалізації (SQL і Firestore) зобов'язані поводитись однаково — за цим
стежить спільний набір тестів у tests_repo.py, який ганяє один і той самий
сценарій через кожну з них.

Правило: сюди потрапляють операції предметної області, а не запити.
`top_spenders(min_total)` — так; `select(...).join(...)` — ні. Інакше SQL
протече в інтерфейс і Firestore його не реалізує.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from decimal import Decimal

from shop.entities import (
    Broadcast, BroadcastStatus, CartLine, Category, Order, OrderLine,
    OrderStatus, Product, Promo, Stats, User,
)


class Repository(ABC):
    """Одна одиниця роботи. Створюється на запит, закривається після нього."""

    # ------------------------------------------------------------ users

    @abstractmethod
    async def get_user_by_tg(self, tg_id: int) -> User | None: ...

    @abstractmethod
    async def get_user(self, user_id: int) -> User | None: ...

    @abstractmethod
    async def get_user_by_referral_code(self, code: str) -> User | None: ...

    @abstractmethod
    async def create_user(
        self, tg_id: int, username: str | None, first_name: str | None, referrer_id: int | None
    ) -> User: ...

    @abstractmethod
    async def touch_user(self, user: User, username: str | None, first_name: str | None) -> User:
        """Оновлює last_seen_at та профільні поля."""

    @abstractmethod
    async def set_user_referrer(self, user: User, referrer_id: int) -> None: ...

    @abstractmethod
    async def confirm_age(self, user: User) -> None: ...

    @abstractmethod
    async def set_blocked(self, user_id: int, blocked: bool) -> User | None: ...

    @abstractmethod
    async def add_bonus(
        self, user_id: int, amount: Decimal, reason: str, order_id: int | None = None
    ) -> None:
        """Змінює баланс і пише запис в історію. amount може бути від'ємним."""

    @abstractmethod
    async def update_user_totals(
        self, user_id: int, orders_delta: int, spent_delta: Decimal
    ) -> None:
        """Атомарно рухає денормалізовані лічильники покупок клієнта."""

    @abstractmethod
    async def list_users(
        self, search: str | None = None, blocked: bool | None = None,
        limit: int = 100, offset: int = 0,
    ) -> list[User]: ...

    # ---------------------------------------------------------- catalog

    @abstractmethod
    async def list_categories(self, only_active: bool = False) -> list[Category]: ...

    @abstractmethod
    async def get_category(self, category_id: int) -> Category | None: ...

    @abstractmethod
    async def create_category(self, data: dict) -> Category: ...

    @abstractmethod
    async def update_category(self, category_id: int, data: dict) -> Category | None: ...

    @abstractmethod
    async def purge_category(self, category_id: int) -> int:
        """Стирає категорію і всі її товари НАЗАВЖДИ. Повертає кількість товарів.

        Історія замовлень не страждає: позиції зберігають знімок назви й ціни,
        а посилання на товар обнуляється.
        """

    @abstractmethod
    async def purge_product(self, product_id: int) -> bool:
        """Стирає товар назавжди. Прибирає його з кошиків і знеособлює в історії."""

    @abstractmethod
    async def purge_promo(self, promo_id: int) -> bool:
        """Стирає промокод назавжди разом з історією його застосувань.

        Замовлення, оформлені з ним, лишаються — у них обнуляється посилання.
        """

    @abstractmethod
    async def delete_category(self, category_id: int) -> int:
        """Ховає категорію разом із її товарами. Повертає кількість схованих товарів.

        Семантика та сама, що в товарів і промокодів: запис лишається в базі,
        але зникає з бота. Інакше історія замовлень посилалася б у порожнечу.
        """

    @abstractmethod
    async def list_products(
        self, category_id: int | None = None, search: str | None = None,
        only_active: bool = False, limit: int = 500, offset: int = 0,
    ) -> list[Product]: ...

    @abstractmethod
    async def count_products(self, category_id: int, only_active: bool = True) -> int: ...

    @abstractmethod
    async def get_product(self, product_id: int) -> Product | None: ...

    @abstractmethod
    async def create_product(self, data: dict) -> Product: ...

    @abstractmethod
    async def update_product(self, product_id: int, data: dict) -> Product | None: ...

    @abstractmethod
    async def adjust_stock(self, product_id: int, delta: int) -> Product | None:
        """Зсув залишку. Атомарний — два замовлення одночасно не вийдуть у мінус."""

    @abstractmethod
    async def set_stock(self, product_id: int, stock: int) -> Product | None: ...

    @abstractmethod
    async def count_low_stock(self, threshold: int = 5) -> int: ...

    # ------------------------------------------------------------- cart

    @abstractmethod
    async def get_cart(self, user_id: int) -> list[CartLine]: ...

    @abstractmethod
    async def set_cart_qty(self, user_id: int, product_id: int, qty: int) -> None: ...

    @abstractmethod
    async def clear_cart(self, user_id: int) -> None: ...

    # ----------------------------------------------------------- orders

    @abstractmethod
    async def create_order(self, order: Order, lines: list[OrderLine]) -> Order: ...

    @abstractmethod
    async def get_order(self, order_id: int) -> Order | None: ...

    @abstractmethod
    async def list_orders(
        self, status: OrderStatus | None = None, search: str | None = None,
        user_id: int | None = None, limit: int = 100, offset: int = 0,
    ) -> list[Order]: ...

    @abstractmethod
    async def update_order(self, order_id: int, data: dict) -> Order | None: ...

    @abstractmethod
    async def count_orders(self, status: OrderStatus | None = None) -> int: ...

    @abstractmethod
    async def status_breakdown(self) -> dict[str, int]: ...

    # ----------------------------------------------------------- promos

    @abstractmethod
    async def get_promo_by_code(self, code: str) -> Promo | None: ...

    @abstractmethod
    async def get_promo(self, promo_id: int) -> Promo | None: ...

    @abstractmethod
    async def list_promos(self) -> list[Promo]: ...

    @abstractmethod
    async def create_promo(self, data: dict) -> Promo: ...

    @abstractmethod
    async def update_promo(self, promo_id: int, data: dict) -> Promo | None: ...

    @abstractmethod
    async def promo_uses_by_user(self, promo_id: int, user_id: int) -> int: ...

    @abstractmethod
    async def register_promo_use(self, promo_id: int, user_id: int, order_id: int) -> None: ...

    # ------------------------------------------------------- broadcasts

    @abstractmethod
    async def list_broadcasts(self) -> list[Broadcast]: ...

    @abstractmethod
    async def get_broadcast(self, broadcast_id: int) -> Broadcast | None: ...

    @abstractmethod
    async def create_broadcast(self, data: dict) -> Broadcast: ...

    @abstractmethod
    async def update_broadcast(self, broadcast_id: int, data: dict) -> Broadcast | None: ...

    @abstractmethod
    async def delete_broadcast(self, broadcast_id: int) -> bool: ...

    @abstractmethod
    async def next_pending_broadcast(self) -> Broadcast | None: ...

    # --------------------------------------------------------- segments

    @abstractmethod
    async def count_segment(self, segment: dict) -> int: ...

    @abstractmethod
    async def segment_recipients(
        self, segment: dict, cursor_id: int, limit: int
    ) -> list[tuple[int, int]]:
        """Наступна порція як (user_id, tg_id), впорядкована за user_id."""

    # ------------------------------------------------------------ stats

    @abstractmethod
    async def stats_summary(self, days: int) -> Stats: ...

    @abstractmethod
    async def stats_series(self, days: int) -> list[dict]:
        """[{date: 'YYYY-MM-DD', revenue: Decimal, orders: int}, ...]"""

    @abstractmethod
    async def stats_top_products(self, days: int, limit: int) -> list[dict]: ...

    # --------------------------------------------------- налаштування

    @abstractmethod
    async def get_settings_map(self) -> dict[str, str]:
        """Налаштування, збережені з панелі. Порожній dict — нічого не задано."""

    @abstractmethod
    async def save_settings_map(self, values: dict[str, str]) -> None:
        """Перезаписує передані ключі, не чіпаючи решту."""

    # ------------------------------------------------------ lifecycle

    async def close(self) -> None:
        """Звільнення ресурсів. За замовчуванням нічого не робить."""
