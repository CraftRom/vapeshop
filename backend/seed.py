"""Наповнює каталог демо-даними.

Працює з будь-якою базою: DB_BACKEND визначає, куди саме писати.
    docker compose exec bot python seed.py
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

from shop.config import settings
from shop.entities import PromoType
from shop.repo.factory import open_repo

CATALOG = {
    "Одноразові поди": [
        ("Elf Bar BC5000", "5000 затяжок, 13 мл, акумулятор 650 mAh", 420, 40),
        ("Elf Bar BC10000", "10000 затяжок, дисплей заряду, Type-C", 620, 25),
        ("Lost Mary OS5000", "5000 затяжок, сітчастий випарник", 480, 30),
    ],
    "Багаторазові пристрої": [
        ("Vaporesso XROS 3", "1000 mAh, регулювання потоку повітря", 890, 15),
        ("Uwell Caliburn G3", "900 mAh, змінні картриджі 2 мл", 950, 12),
    ],
    "Рідини": [
        ("Рідина 30 мл, 50 мг", "Сольовий нікотин, банка 30 мл", 260, 60),
        ("Рідина 15 мл, 30 мг", "Сольовий нікотин, банка 15 мл", 180, 45),
    ],
    "Картриджі та аксесуари": [
        ("Картридж XROS, 2 шт", "Сумісний з XROS 1/2/3", 190, 50),
        ("Кабель Type-C", "Для заряджання пристроїв", 90, 100),
    ],
}

PROMOS = [
    {"code": "WELCOME10", "type": PromoType.PERCENT, "value": Decimal(10),
     "min_order": Decimal(500), "max_uses": None, "per_user_limit": 1},
    {"code": "OPT500", "type": PromoType.FIXED, "value": Decimal(500),
     "min_order": Decimal(5000), "max_uses": 50, "per_user_limit": 3},
]


async def main() -> None:
    if settings.db_backend == "sql":
        from shop.db import init_db
        await init_db()

    async with open_repo() as repo:
        if await repo.list_categories():
            print("У базі вже є дані — сідинг пропущено.")
            return

        for order, (name, products) in enumerate(CATALOG.items()):
            category = await repo.create_category(
                {"name": name, "sort_order": order, "is_active": True}
            )
            for p_order, (p_name, description, price, stock) in enumerate(products):
                await repo.create_product({
                    "category_id": category.id, "name": p_name,
                    "description": description, "price": Decimal(price),
                    "stock": stock, "sort_order": p_order, "is_active": True,
                })

        for promo in PROMOS:
            await repo.create_promo(promo | {"is_active": True})

        print(f"Готово: {len(CATALOG)} категорій, {len(PROMOS)} промокоди "
              f"(база: {settings.db_backend}).")


if __name__ == "__main__":
    asyncio.run(main())
