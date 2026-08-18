"""Наскрізний тест логіки магазину на SQLite.

Запуск:  python tests_smoke.py
Перевіряє кошик, промокоди, бонуси, реферальну винагороду й повернення залишків.
"""
from __future__ import annotations

import asyncio
import os
from decimal import Decimal

os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test" * 8)

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from shop.models import (  # noqa: E402
    Base, Category, Order, OrderStatus, Product, PromoCode, PromoType,
)
from shop.services import cart as cart_service  # noqa: E402
from shop.services import orders as order_service  # noqa: E402
from shop.services import promo as promo_service  # noqa: E402
from shop.services import segments as segment_service  # noqa: E402
from shop.services import users as users_service  # noqa: E402

passed = failed = 0


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {label}")
    else:
        failed += 1
        print(f"  ✗ {label}  {detail}")


async def main() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as s:
        # --- підготовка каталогу
        category = Category(name="Одноразові поди")
        s.add(category)
        await s.flush()
        pod = Product(category_id=category.id, name="Elf Bar BC5000", price=Decimal(400), stock=10)
        liquid = Product(category_id=category.id, name="Рідина 30 мл", price=Decimal(250), stock=4)
        s.add_all([pod, liquid])
        s.add(
            PromoCode(
                code="WELCOME10", type=PromoType.PERCENT, value=Decimal(10),
                min_order=Decimal(500), per_user_limit=1,
            )
        )
        await s.commit()

        print("\nРеферальний зв'язок")
        referrer, _ = await users_service.get_or_create_user(s, 1001, "referrer", "Ігор")
        buyer, is_new = await users_service.get_or_create_user(
            s, 1002, "buyer", "Оля", referral_code=referrer.referral_code
        )
        check("нового користувача створено", is_new)
        check("реферера прив'язано", buyer.referrer_id == referrer.id)
        check("коди рефералів різні", referrer.referral_code != buyer.referral_code)

        print("\nКошик")
        await cart_service.add(s, buyer.id, pod.id, 2)
        await cart_service.add(s, buyer.id, liquid.id, 1)
        check("сума кошика 1050", await cart_service.subtotal(s, buyer.id) == Decimal(1050))

        await cart_service.add(s, buyer.id, liquid.id, 99)
        items = {i.product_id: i.qty for i in await cart_service.get_items(s, buyer.id)}
        check("кількість обрізана до залишку", items[liquid.id] == 4, f"отримано {items[liquid.id]}")

        await cart_service.set_qty(s, buyer.id, liquid.id, 1)

        print("\nПромокоди")
        ok = await promo_service.apply(s, "welcome10", buyer.id, Decimal(1050))
        check("код нечутливий до регістру", ok.ok)
        check("знижка 10% = 105", ok.discount == Decimal("105.00"), f"отримано {ok.discount}")

        small = await promo_service.apply(s, "WELCOME10", buyer.id, Decimal(300))
        check("мінімальна сума спрацювала", not small.ok and "Мінімальна" in small.error)

        missing = await promo_service.apply(s, "NOPE", buyer.id, Decimal(1050))
        check("неіснуючий код відхилено", not missing.ok)

        print("\nОформлення замовлення")
        order, error = await order_service.create_from_cart(
            s, buyer,
            contact_name="Оля К.", contact_phone="+380671112233",
            city="Хмельницький", address="Відділення №5",
            payment_method="card", promo_code="WELCOME10",
        )
        check("замовлення створено", order is not None, str(error))
        check("сума до знижки 1050", order.subtotal == Decimal(1050))
        check("знижка 105", order.discount == Decimal("105.00"))
        check("до сплати 945", order.total == Decimal("945.00"), f"отримано {order.total}")

        await s.refresh(pod)
        await s.refresh(liquid)
        check("залишок подів 10−2=8", pod.stock == 8, f"отримано {pod.stock}")
        check("залишок рідини 4−1=3", liquid.stock == 3, f"отримано {liquid.stock}")
        check("кошик очищено", not await cart_service.get_items(s, buyer.id))

        repeat = await promo_service.apply(s, "WELCOME10", buyer.id, Decimal(1050))
        check("повторне використання коду заблоковано", not repeat.ok)

        print("\nРеферальна винагорода")
        reward = await order_service.change_status(s, order, OrderStatus.DONE)
        await s.refresh(referrer)
        check("нараховано 5% = 47.25", reward == Decimal("47.25"), f"отримано {reward}")
        check("баланс реферера оновлено", referrer.bonus_balance == Decimal("47.25"))

        again = await order_service.change_status(s, order, OrderStatus.DONE)
        await s.refresh(referrer)
        check("подвійного нарахування немає", again is None and referrer.bonus_balance == Decimal("47.25"))

        print("\nСписання бонусів")
        cap = order_service.max_bonus_for(Decimal(1000), Decimal(500))
        check("списання обмежене 30% від суми", cap == Decimal("300.00"), f"отримано {cap}")
        cap_small = order_service.max_bonus_for(Decimal(1000), Decimal(50))
        check("списання не більше балансу", cap_small == Decimal(50))

        await cart_service.add(s, referrer.id, pod.id, 1)
        order2, error2 = await order_service.create_from_cart(
            s, referrer,
            contact_name="Ігор П.", contact_phone="+380671112244",
            city="Київ", address="Відділення №1",
            payment_method="cod", use_bonus=True,
        )
        check("друге замовлення створено", order2 is not None, str(error2))
        check("бонуси списано 47.25", order2.bonus_used == Decimal("47.25"))
        check("до сплати 400−47.25=352.75", order2.total == Decimal("352.75"), f"отримано {order2.total}")
        await s.refresh(referrer)
        check("баланс обнулено", referrer.bonus_balance == Decimal("0.00"))

        print("\nСкасування замовлення")
        await order_service.change_status(s, order2, OrderStatus.CANCELLED)
        await s.refresh(pod)
        await s.refresh(referrer)
        check("залишок повернуто 7→8", pod.stock == 8, f"отримано {pod.stock}")
        check("бонуси повернуто", referrer.bonus_balance == Decimal("47.25"))

        print("\nСегментація")
        all_users = await segment_service.count(s, {"type": "all"})
        check("age_confirmed фільтрує всіх", all_users == 0, f"отримано {all_users}")

        buyer.age_confirmed = True
        referrer.age_confirmed = True
        await s.commit()

        check("усі клієнти = 2", await segment_service.count(s, {"type": "all"}) == 2)
        check("з покупками = 1", await segment_service.count(s, {"type": "with_orders"}) == 1)
        check("без покупок = 1", await segment_service.count(s, {"type": "no_orders"}) == 1)
        check("привели друзів = 1", await segment_service.count(s, {"type": "with_referrals"}) == 1)
        check(
            "витратили від 500 = 1",
            await segment_service.count(s, {"type": "top_spenders", "min_total": 500}) == 1,
        )
        check(
            "витратили від 5000 = 0",
            await segment_service.count(s, {"type": "top_spenders", "min_total": 5000}) == 0,
        )

        print("\nПорожній кошик")
        empty_order, empty_error = await order_service.create_from_cart(
            s, buyer,
            contact_name="Оля", contact_phone="+380671112233",
            city="Хмельницький", address="Відділення №5", payment_method="card",
        )
        check("порожній кошик відхилено", empty_order is None and "порожній" in empty_error)

    await engine.dispose()
    print(f"\n{'=' * 46}\nПройдено: {passed}   Провалено: {failed}\n{'=' * 46}")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
