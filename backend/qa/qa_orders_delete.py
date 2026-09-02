"""ВИДАЛЕННЯ ЗАМОВЛЕНЬ: лише системний адміністратор, лише свідомо."""
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, "/tmp")
os.environ.update(BOT_TOKEN="777001:T", JWT_SECRET="t" * 32,
                  DASHBOARD_LOGIN="root", DASHBOARD_PASSWORD="Pa$$w0rd123",
                  ELFAR_DATA_ROOT=tempfile.mkdtemp(prefix="qa_ordel_"),
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_ordel.db")

from qa_common import Report, seed_operators                              # noqa: E402

r = Report("ВИДАЛЕННЯ ЗАМОВЛЕНЬ")

import httpx                                              # noqa: E402
from api.auth import create_token                         # noqa: E402
from api.main import app                                  # noqa: E402
from decimal import Decimal                               # noqa: E402

from shop.entities import OperatorRole, Order, OrderLine  # noqa: E402
from shop.repo.factory import open_repo                   # noqa: E402

SYSADMIN = create_token("root", OperatorRole.SYSADMIN, 0, "Root")
ADMIN = create_token("shopadmin", OperatorRole.ADMIN, 5, "Адмін")
MANAGER = create_token("manager", OperatorRole.MANAGER, 7, "Менеджер")


async def make_order(repo, tg_id: int):
    """Клієнт із одним замовленням — мінімум, потрібний для перевірки."""
    user = await repo.create_user(tg_id, f"u{tg_id}", "U", None)
    category = await repo.create_category({"name": f"Кат{tg_id}"})
    product = await repo.create_product({
        "name": f"Товар{tg_id}", "category_id": category.id,
        "price": Decimal(100), "stock": 10, "is_active": True,
    })
    order = await repo.create_order(
        Order(id=0, user_id=user.id, subtotal=Decimal(100), discount=Decimal(0),
              bonus_used=Decimal(0), total=Decimal(100), promo_code_id=None,
              payment_method="cod", contact_name="Тест",
              contact_phone="+380671112233"),
        [OrderLine(product_id=product.id, name=product.name,
                   price=Decimal(100), qty=1)],
    )
    # Підсумки клієнта проставляємо явно: саме їх має обнулити повне
    # видалення, і без них перевірка була б беззмістовною.
    await repo.update_user_totals(user.id, orders_delta=1, spent_delta=Decimal(100))
    return user, order


async def scenario():
    from shop.db import init_db

    await init_db()

    async with open_repo() as _repo:
        await seed_operators(_repo, {
            5: ("shopadmin", "Адмін", OperatorRole.ADMIN),
            7: ("manager", "Менеджер", OperatorRole.MANAGER),
        })
    transport = httpx.ASGITransport(app=app)

    async with open_repo() as repo:
        _, first = await make_order(repo, 5001)
        _, second = await make_order(repo, 5002)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        def head(token):
            return {"Authorization": f"Bearer {token}"}

        print("\n--- права ---")
        for label, token in [("менеджер", MANAGER), ("адміністратор", ADMIN)]:
            resp = await client.delete(f"/api/orders/{first.id}", headers=head(token))
            r.check(resp.status_code == 403, f"{label} не видаляє замовлення",
                    resp.status_code)

        resp = await client.delete(f"/api/orders/{first.id}")
        r.check(resp.status_code in (401, 403), "без токена не пускає", resp.status_code)

        async with open_repo() as repo:
            still = await repo.get_order(first.id)
        r.check(still is not None, "після відмов замовлення на місці")

        print("\n--- видалення одного ---")
        resp = await client.delete(f"/api/orders/{first.id}", headers=head(SYSADMIN))
        r.check(resp.status_code == 204, "видалено", resp.status_code)

        async with open_repo() as repo:
            gone = await repo.get_order(first.id)
            kept = await repo.get_order(second.id)
        r.check(gone is None, "замовлення справді стерто")
        r.check(kept is not None, "сусіднє не зачеплено")

        resp = await client.delete(f"/api/orders/{first.id}", headers=head(SYSADMIN))
        r.check(resp.status_code == 404, "повторне видалення — 404", resp.status_code)

        print("\n--- видалення всіх вимагає підтвердження ---")
        # Відновити це можна лише з резервної копії, а вона може бути
        # вчорашньою. Тому підтвердження — точний рядок, а не прапорець.
        for wrong in ("", "yes", "delete all", "DELETE", "ТАК"):
            resp = await client.delete(f"/api/orders?confirm={wrong}",
                                       headers=head(SYSADMIN))
            r.check(resp.status_code == 400, f"відхилено: {wrong!r}", resp.status_code)

        resp = await client.delete("/api/orders?confirm=DELETE ALL", headers=head(MANAGER))
        r.check(resp.status_code == 403, "менеджер не стирає все")

        print("\n--- видалення всіх ---")
        resp = await client.delete("/api/orders?confirm=DELETE ALL", headers=head(SYSADMIN))
        r.check(resp.status_code == 200, "виконано", resp.status_code)
        r.check(resp.json()["removed"] == 1, "повернуто кількість", resp.json())

        async with open_repo() as repo:
            rest = await repo.list_orders()
            user = await repo.get_user_by_tg(5002)
        r.check(not rest, "замовлень не лишилось", len(rest))
        # Інакше в картці клієнта висіло б «1 замовлення», якого немає
        r.check(user.orders_count == 0, "підсумки клієнта обнулені", user.orders_count)


asyncio.run(scenario())
r.done()
