"""Контрактні тести: один сценарій — дві бази.

Сенс у тому, що кожна перевірка виконується двічі: через SqlRepository
(SQLite) і через FirestoreRepository (InMemoryDocStore). Якщо реалізації
почнуть розходитись — тест це покаже одразу, а не в продакшені.

Запуск:  python tests_repo.py
Проти справжнього Firestore:  FIRESTORE_EMULATOR_HOST=localhost:8080 python tests_repo.py --real
"""
from __future__ import annotations

import asyncio
import os
import sys
from decimal import Decimal

os.environ.setdefault("BOT_TOKEN", "1:test")
os.environ.setdefault("JWT_SECRET", "t" * 32)
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from shop.entities import OrderStatus, PromoType  # noqa: E402
from shop.models import Base  # noqa: E402
from shop.repo.docstore import InMemoryDocStore  # noqa: E402
from shop.repo.firestore import FirestoreRepository  # noqa: E402
from shop.repo.sql import SqlRepository  # noqa: E402
from shop.services import shop_service as svc  # noqa: E402

results: dict[str, list[tuple[str, bool, str]]] = {}
current = ""


def check(label: str, condition: bool, detail: str = "") -> None:
    results.setdefault(current, []).append((label, bool(condition), detail))


# ------------------------------------------------------------------- сценарій

async def scenario(repo) -> None:
    # --- каталог
    category = await repo.create_category({"name": "Поди", "sort_order": 0, "is_active": True})
    check("категорія створена", category.id > 0)

    pod = await repo.create_product({
        "category_id": category.id, "name": "Elf Bar BC5000",
        "price": Decimal(400), "stock": 10, "is_active": True,
    })
    liquid = await repo.create_product({
        "category_id": category.id, "name": "Рідина 30 мл",
        "price": Decimal(250), "stock": 4, "is_active": True,
    })
    check("товар створений з ціною 400", pod.price == Decimal("400.00"), f"{pod.price}")

    cats = await repo.list_categories()
    check("лічильник товарів у категорії = 2", cats[0].products_count == 2,
          f"{cats[0].products_count}")

    found = await repo.list_products(search="elf")
    check("префіксний пошук знаходить товар", len(found) == 1 and found[0].id == pod.id,
          f"знайдено {len(found)}")

    check("мало залишків: 0 при порозі 4", await repo.count_low_stock(4) == 0)
    check("мало залишків: 1 при порозі 5", await repo.count_low_stock(5) == 1)

    # --- користувачі й реферали
    referrer, is_new = await svc.get_or_create_user(repo, 1001, "ref", "Ігор")
    check("новий користувач створений", is_new)

    buyer, _ = await svc.get_or_create_user(
        repo, 1002, "buyer", "Оля", referral_code=referrer.referral_code
    )
    check("реферера прив'язано", buyer.referrer_id == referrer.id)

    referrer = await repo.get_user(referrer.id)
    check("лічильник рефералів = 1", referrer.referrals_count == 1,
          f"{referrer.referrals_count}")

    again, is_new2 = await svc.get_or_create_user(repo, 1002, "buyer", "Оля")
    check("повторний /start не дублює користувача", not is_new2 and again.id == buyer.id)

    # --- кошик
    await svc.add_to_cart(repo, buyer.id, pod.id, 2)
    await svc.add_to_cart(repo, buyer.id, liquid.id, 1)
    check("сума кошика 1050", await svc.cart_subtotal(repo, buyer.id) == Decimal(1050),
          f"{await svc.cart_subtotal(repo, buyer.id)}")

    await svc.add_to_cart(repo, buyer.id, liquid.id, 99)
    lines = {ln.product_id: ln.qty for ln in await repo.get_cart(buyer.id)}
    check("кількість обрізана до залишку", lines[liquid.id] == 4, f"{lines[liquid.id]}")
    await repo.set_cart_qty(buyer.id, liquid.id, 1)

    # --- промокоди
    await repo.create_promo({
        "code": "WELCOME10", "type": PromoType.PERCENT, "value": Decimal(10),
        "min_order": Decimal(500), "per_user_limit": 1, "is_active": True,
    })
    ok = await svc.check_promo(repo, "welcome10", buyer.id, Decimal(1050))
    check("код нечутливий до регістру", ok.ok, str(ok.error))
    check("знижка 10% = 105", ok.discount == Decimal("105.00"), f"{ok.discount}")

    small = await svc.check_promo(repo, "WELCOME10", buyer.id, Decimal(300))
    check("мінімальна сума спрацювала", not small.ok)

    missing = await svc.check_promo(repo, "NOPE", buyer.id, Decimal(1050))
    check("неіснуючий код відхилено", not missing.ok)

    # --- замовлення
    order, error = await svc.create_order(
        repo, buyer, contact_name="Оля К.", contact_phone="+380671112233",
        city="Хмельницький", address="Відділення №5",
        payment_method="card", promo_code="WELCOME10",
    )
    check("замовлення створене", order is not None, str(error))
    check("сума 1050", order.subtotal == Decimal("1050.00"), f"{order.subtotal}")
    check("знижка 105", order.discount == Decimal("105.00"), f"{order.discount}")
    check("до сплати 945", order.total == Decimal("945.00"), f"{order.total}")
    check("позиції збережені", len(order.items) == 2, f"{len(order.items)}")

    check("залишок подів 8", (await repo.get_product(pod.id)).stock == 8,
          f"{(await repo.get_product(pod.id)).stock}")
    check("залишок рідини 3", (await repo.get_product(liquid.id)).stock == 3)
    check("кошик очищено", not await repo.get_cart(buyer.id))

    repeat = await svc.check_promo(repo, "WELCOME10", buyer.id, Decimal(1050))
    check("повторне використання коду заблоковано", not repeat.ok)

    # --- статуси й лічильники
    await svc.change_order_status(repo, order, OrderStatus.PAID)
    buyer_now = await repo.get_user(buyer.id)
    check("orders_count = 1 після оплати", buyer_now.orders_count == 1,
          f"{buyer_now.orders_count}")
    check("total_spent = 945", buyer_now.total_spent == Decimal("945.00"),
          f"{buyer_now.total_spent}")

    reward = await svc.change_order_status(repo, order, OrderStatus.DONE)
    check("реферальна винагорода 47.25", reward == Decimal("47.25"), f"{reward}")

    referrer_now = await repo.get_user(referrer.id)
    check("баланс реферера 47.25", referrer_now.bonus_balance == Decimal("47.25"),
          f"{referrer_now.bonus_balance}")

    again_reward = await svc.change_order_status(repo, order, OrderStatus.DONE)
    check("подвійного нарахування немає", again_reward is None)

    check("orders_count не подвоївся", (await repo.get_user(buyer.id)).orders_count == 1)

    # --- бонуси
    check("списання обмежене 30%", svc.max_bonus_for(Decimal(1000), Decimal(500))
          == Decimal("300.00"))
    check("списання не більше балансу", svc.max_bonus_for(Decimal(1000), Decimal(50))
          == Decimal(50))

    referrer_now = await repo.get_user(referrer.id)
    await svc.add_to_cart(repo, referrer_now.id, pod.id, 1)
    order2, error2 = await svc.create_order(
        repo, referrer_now, contact_name="Ігор П.", contact_phone="+380671112244",
        city="Київ", address="Відділення №1", payment_method="cod", use_bonus=True,
    )
    check("друге замовлення створене", order2 is not None, str(error2))
    check("бонуси списані 47.25", order2.bonus_used == Decimal("47.25"), f"{order2.bonus_used}")
    check("до сплати 352.75", order2.total == Decimal("352.75"), f"{order2.total}")
    check("баланс обнулено", (await repo.get_user(referrer.id)).bonus_balance == Decimal(0),
          f"{(await repo.get_user(referrer.id)).bonus_balance}")

    # --- скасування
    await svc.change_order_status(repo, order2, OrderStatus.PAID)
    await svc.change_order_status(repo, order2, OrderStatus.CANCELLED)
    check("залишок повернуто", (await repo.get_product(pod.id)).stock == 8,
          f"{(await repo.get_product(pod.id)).stock}")
    check("бонуси повернуто", (await repo.get_user(referrer.id)).bonus_balance
          == Decimal("47.25"))
    check("orders_count відкотився", (await repo.get_user(referrer.id)).orders_count == 0,
          f"{(await repo.get_user(referrer.id)).orders_count}")

    # --- пошук і списки
    orders = await repo.list_orders(search="0671112233")
    check("пошук замовлення за телефоном", len(orders) == 1 and orders[0].id == order.id,
          f"знайдено {len(orders)}")
    check("фільтр за статусом", len(await repo.list_orders(status=OrderStatus.DONE)) == 1)
    check("розподіл за статусами", (await repo.status_breakdown()).get("done") == 1)
    check("пошук клієнта за іменем", len(await repo.list_users(search="Оля")) == 1)

    # --- сегменти
    check("усі клієнти = 0 без підтвердження віку",
          await repo.count_segment({"type": "all"}) == 0)

    for user in (buyer, referrer):
        entity = await repo.get_user(user.id)
        await repo.confirm_age(entity)

    check("усі клієнти = 2", await repo.count_segment({"type": "all"}) == 2,
          f"{await repo.count_segment({'type': 'all'})}")
    check("з покупками = 1", await repo.count_segment({"type": "with_orders"}) == 1,
          f"{await repo.count_segment({'type': 'with_orders'})}")
    check("без покупок = 1", await repo.count_segment({"type": "no_orders"}) == 1)
    check("привели друзів = 1", await repo.count_segment({"type": "with_referrals"}) == 1)
    check("витратили від 500 = 1",
          await repo.count_segment({"type": "top_spenders", "min_total": 500}) == 1)
    check("витратили від 5000 = 0",
          await repo.count_segment({"type": "top_spenders", "min_total": 5000}) == 0)

    # --- курсор розсилки
    first = await repo.segment_recipients({"type": "all"}, 0, 1)
    check("порція з 1 отримувача", len(first) == 1, f"{len(first)}")
    second = await repo.segment_recipients({"type": "all"}, first[0][0], 10)
    check("курсор рухається вперед", len(second) == 1 and second[0][0] > first[0][0])
    check("після останнього порожньо",
          not await repo.segment_recipients({"type": "all"}, second[0][0], 10))

    # --- статистика
    stats = await repo.stats_summary(30)
    check("виручка 945", stats.revenue_total == Decimal("945.00"), f"{stats.revenue_total}")
    check("клієнтів 2", stats.customers_total == 2)
    check("середній чек 945", stats.avg_check == Decimal("945.00"), f"{stats.avg_check}")

    series = await repo.stats_series(30)
    check("графік має 1 день", len(series) == 1, f"{len(series)}")
    check("виручка в графіку 945", series[0]["revenue"] == Decimal("945.00"))

    top = await repo.stats_top_products(30, 10)
    check("топ товарів заповнений", len(top) == 2, f"{len(top)}")
    check("лідер — под на 800", top[0]["revenue"] == Decimal("800.00"), f"{top[0]}")

    # --- порожній кошик
    empty, empty_error = await svc.create_order(
        repo, await repo.get_user(buyer.id), contact_name="Оля",
        contact_phone="+380671112233", city="Х", address="В5", payment_method="card",
    )
    check("порожній кошик відхилено", empty is None and "порожній" in empty_error)


# ---------------------------------------------------------------------- запуск

async def run_sql() -> None:
    global current
    current = "SQL (SQLite)"
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as session:
        await scenario(SqlRepository(session))
    await engine.dispose()


async def run_firestore() -> None:
    global current
    current = "Firestore (in-memory)"
    await scenario(FirestoreRepository(InMemoryDocStore()))


async def run_firestore_real() -> None:
    global current
    current = "Firestore (емулятор)"
    from shop.repo.firestore_store import FirestoreDocStore
    store = FirestoreDocStore(project=os.environ.get("FIREBASE_PROJECT", "demo-shop"))
    await scenario(FirestoreRepository(store))
    await store.close()


async def main() -> None:
    await run_sql()
    if "--real" in sys.argv:
        await run_firestore_real()
    else:
        await run_firestore()

    total_failed = 0
    for backend, checks in results.items():
        failed = [c for c in checks if not c[1]]
        total_failed += len(failed)
        print(f"\n{'=' * 60}\n{backend}\n{'=' * 60}")
        for label, ok, detail in checks:
            if not ok:
                print(f"  ✗ {label}   {detail}")
        print(f"  Пройдено {len(checks) - len(failed)} з {len(checks)}")

    # Обидві реалізації мають давати однаковий результат по кожній перевірці
    backends = list(results.values())
    if len(backends) == 2:
        mismatches = [
            a[0] for a, b in zip(backends[0], backends[1]) if a[1] != b[1]
        ]
        print(f"\n{'=' * 60}")
        if mismatches:
            print(f"РОЗБІЖНОСТІ МІЖ БАЗАМИ ({len(mismatches)}):")
            for label in mismatches:
                print(f"  • {label}")
            total_failed += len(mismatches)
        else:
            print("Обидві бази поводяться однаково ✓")

    print(f"{'=' * 60}\nВсього провалено: {total_failed}\n")
    raise SystemExit(1 if total_failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
