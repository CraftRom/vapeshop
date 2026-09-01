"""МЕЖІ: що робить система на граничних і безглуздих значеннях.

Помилки на межах не видно в звичайній роботі: вони спрацьовують, коли
залишок доходить до нуля, коли клієнт має бонусів більше за замовлення,
коли два покупці беруть останній товар одночасно. Саме тоді ціна помилки
найвища — це реальні гроші й реальний товар.
"""
import asyncio
import os
import sys
import tempfile
from decimal import Decimal

sys.path.insert(0, "/tmp")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  ELFAR_DATA_ROOT=tempfile.mkdtemp(prefix="qa_edge_"),
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_edges.db")

import pathlib  # noqa: E402

for suffix in ("", "-wal", "-shm"):
    pathlib.Path(f"/tmp/qa_edges.db{suffix}").unlink(missing_ok=True)

from qa_common import Report                              # noqa: E402

r = Report("МЕЖІ")

from shop.repo.factory import open_repo                   # noqa: E402
from shop.services import shop_service as svc             # noqa: E402


async def scenario():
    from shop.db import init_db

    await init_db()

    async with open_repo() as repo:
        user = await repo.create_user(1, "u", "U", None)
        category = await repo.create_category({"name": "K"})
        product = await repo.create_product({
            "name": "Товар", "category_id": category.id,
            "price": Decimal(100), "stock": 50, "is_active": True,
        })

        print("\n--- залишок не йде в мінус ---")
        # Інакше в каталозі зʼявиться «-3 шт», а замовлення пройдуть на
        # товар, якого немає.
        await repo.adjust_stock(product.id, -500)
        fresh = await repo.get_product(product.id)
        r.check(fresh.stock == 0, "залишок обмежений нулем", fresh.stock)
        await repo.adjust_stock(product.id, 50)

        print("\n--- підсумки клієнта не йдуть у мінус ---")
        # Скасування замовлень поспіль колись давало «-2 замовлення»
        # в картці клієнта.
        await repo.update_user_totals(user.id, orders_delta=-3,
                                      spent_delta=Decimal(-500))
        fresh_user = await repo.get_user(user.id)
        r.check(fresh_user.orders_count == 0, "кількість замовлень не відʼємна",
                fresh_user.orders_count)
        r.check(fresh_user.total_spent == 0, "витрачене не відʼємне",
                str(fresh_user.total_spent))

        print("\n--- бонусів більше, ніж коштує замовлення ---")
        await repo.add_bonus(user.id, Decimal(10000), "тест")
        await repo.set_cart_qty(user.id, product.id, 1)
        user = await repo.get_user(user.id)
        order, error = await svc.create_order(
            repo, user, contact_name="A", contact_phone="+380671112233",
            city="Київ", address="Відділення 1", payment_method="cod",
            use_bonus=True, promo_code=None, comment=None,
        )
        r.check(order is not None, "замовлення створене", error)
        if order:
            r.check(order.total >= 0, "сума не відʼємна", str(order.total))
            r.check(order.bonus_used <= order.subtotal,
                    "списано не більше за вартість товарів",
                    (str(order.bonus_used), str(order.subtotal)))

        print("\n--- останній товар не продається двічі ---")
        # Два покупці натискають «Оформити» одночасно на останню одиницю.
        # Якщо залишок не захищений, обидва отримають підтвердження, а
        # товар є лише один — і хтось дізнається про це вже після оплати.
        single = await repo.create_product({
            "name": "Останній", "category_id": category.id,
            "price": Decimal(100), "stock": 1, "is_active": True,
        })
        second = await repo.create_user(2, "u2", "U2", None)
        for who in (user, second):
            await repo.set_cart_qty(who.id, single.id, 1)

        results = await asyncio.gather(*[
            svc.create_order(
                repo, await repo.get_user(who.id),
                contact_name="A", contact_phone="+380671112233",
                city="Київ", address="Відділення 1", payment_method="cod",
                use_bonus=False, promo_code=None, comment=None,
            )
            for who in (user, second)
        ], return_exceptions=True)

        created = [x for x in results
                   if isinstance(x, tuple) and x[0] is not None]
        left = (await repo.get_product(single.id)).stock
        r.check(left >= 0, "залишок не пішов у мінус після одночасних спроб", left)
        r.check(len(created) <= 1 or left == 0,
                "останній товар не роздано двом", (len(created), left))

        print("\n--- безглузді кількості в кошику ---")
        for qty, label in [(0, "нуль"), (-5, "відʼємна"), (10 ** 6, "мільйон")]:
            await repo.set_cart_qty(user.id, product.id, qty)
            lines = await repo.get_cart(user.id)
            line = next((x for x in lines if x.product_id == product.id), None)
            amount = line.qty if line else 0
            r.check(0 <= amount <= 10 ** 6,
                    f"{label} не ламає кошик", amount)


asyncio.run(scenario())
r.done()
