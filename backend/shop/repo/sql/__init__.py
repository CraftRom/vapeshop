"""Репозиторій магазину на SQLAlchemy (PostgreSQL у продакшені, SQLite у тестах).

Раніше це був один файл на ~3 800 рядків. Тепер методи згруповано за
предметними областями в класи-домішки; SqlRepository збирає їх в один клас,
тож для решти коду нічого не змінилося: `from shop.repo.sql import SqlRepository`
і допоміжні функції модуля імпортуються як раніше.
"""
from __future__ import annotations

from shop.repo.sql._common import *  # noqa: F401,F403
from shop.repo.sql._common import __all__ as _COMMON
from shop.repo.sql.users import UsersMixin
from shop.repo.sql.catalog import CatalogMixin
from shop.repo.sql.cart import CartMixin
from shop.repo.sql.orders import OrdersMixin
from shop.repo.sql.promos import PromosMixin
from shop.repo.sql.broadcasts import BroadcastsMixin
from shop.repo.sql.stats import StatsMixin
from shop.repo.sql.configuration import ConfigurationMixin
from shop.repo.sql.maintenance import MaintenanceMixin
from shop.repo.sql.order_chat import OrderChatMixin
from shop.repo.sql.wishlists import WishlistsMixin
from shop.repo.sql.support import SupportMixin
from shop.repo.sql.notifications import NotificationsMixin
from shop.repo.sql.staff import StaffMixin


class SqlRepository(UsersMixin, CatalogMixin, CartMixin, OrdersMixin, PromosMixin, BroadcastsMixin, StatsMixin, ConfigurationMixin, MaintenanceMixin, OrderChatMixin, WishlistsMixin, SupportMixin, NotificationsMixin, StaffMixin, Repository):
    def __init__(self, session: AsyncSession) -> None:
        self.s = session

    async def _commit(self) -> None:
        """Фіксує зміни й скидає кеш ORM.

        Частина методів змінює дані атомарним UPDATE повз ORM — так
        безпечніше при одночасних запитах. Але сесія створена з
        expire_on_commit=False, тож у пам'яті лишалася б стара копія
        обʼєкта, і наступне читання в тому ж запиті віддавало б, скажімо,
        доспис бонусів, якого вже немає. Тому після кожного такого запису
        кеш явно скидаємо.
        """
        await self.s.commit()
        self.s.expire_all()


__all__ = ['SqlRepository', *_COMMON]
