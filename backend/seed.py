"""Створює таблиці й наповнює каталог демо-даними.

Запуск:  docker compose exec bot python seed.py
"""
from __future__ import annotations

import asyncio
from decimal import Decimal

from sqlalchemy import select

from shop.db import SessionMaker, init_db
from shop.models import Category, Product, PromoCode, PromoType

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
    ("WELCOME10", PromoType.PERCENT, Decimal(10), Decimal(500), None, 1),
    ("OPT500", PromoType.FIXED, Decimal(500), Decimal(5000), 50, 3),
]


async def main() -> None:
    await init_db()

    async with SessionMaker() as session:
        if await session.scalar(select(Category.id).limit(1)):
            print("У базі вже є дані — сідинг пропущено.")
            return

        for order, (name, products) in enumerate(CATALOG.items()):
            category = Category(name=name, sort_order=order)
            session.add(category)
            await session.flush()

            for p_order, (p_name, description, price, stock) in enumerate(products):
                session.add(
                    Product(
                        category_id=category.id,
                        name=p_name,
                        description=description,
                        price=Decimal(price),
                        stock=stock,
                        sort_order=p_order,
                    )
                )

        for code, ptype, value, min_order, max_uses, per_user in PROMOS:
            session.add(
                PromoCode(
                    code=code,
                    type=ptype,
                    value=value,
                    min_order=min_order,
                    max_uses=max_uses,
                    per_user_limit=per_user,
                )
            )

        await session.commit()
        print("Каталог і промокоди створено.")


if __name__ == "__main__":
    asyncio.run(main())
