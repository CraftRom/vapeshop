"""Наскрізні тести HTTP-шару проти обох баз.

Перевіряє, що API однаково працює і на SQL, і на Firestore: авторизація,
CRUD каталогу, повний цикл замовлення, сегменти, порційна розсилка.

Запуск:  python tests_api.py
"""
from __future__ import annotations

import asyncio
import os
import sys

os.environ.update({
    "BOT_TOKEN": "1:test",
    "JWT_SECRET": "t" * 32,
    "DASHBOARD_LOGIN": "admin",
    "DASHBOARD_PASSWORD": "Пароль123",
    "CRON_SECRET": "cron-secret",
    "WEBHOOK_SECRET": "hook-secret",
})

passed = failed = 0
current = ""


def check(label: str, condition: bool, detail: str = "") -> None:
    global passed, failed
    if condition:
        passed += 1
    else:
        failed += 1
        print(f"  ✗ [{current}] {label}   {detail}")


def run_suite(backend: str) -> None:
    global current
    current = backend

    # Конфіг читається при імпорті, тому модулі перезавантажуємо на кожен бекенд
    for name in [m for m in list(sys.modules) if m.startswith(("shop", "api", "bot"))]:
        del sys.modules[name]

    os.environ["DB_BACKEND"] = backend
    if backend == "sql":
        os.environ["DATABASE_URL"] = "sqlite+aiosqlite:////tmp/api_test.db"
        if os.path.exists("/tmp/api_test.db"):
            os.remove("/tmp/api_test.db")

    if backend == "firestore":
        # Підміняємо сховище на пам'ять — реальний Firestore тут недоступний
        import shop.repo.factory as factory
        from shop.repo.docstore import InMemoryDocStore
        from shop.repo.firestore import FirestoreRepository
        from contextlib import asynccontextmanager

        store = InMemoryDocStore()

        @asynccontextmanager
        async def fake_repo():
            yield FirestoreRepository(store)

        factory.open_repo = fake_repo

        async def dep():
            async with fake_repo() as repo:
                yield repo

        factory.get_repo = dep
        import api.routers.catalog, api.routers.orders, api.routers.customers
        import api.routers.promos, api.routers.stats, api.routers.broadcasts, api.routers.cron

    from api.main import app

    if backend == "firestore":
        from shop.repo.factory import get_repo as real_get_repo
        app.dependency_overrides[real_get_repo] = dep

    asyncio.run(_suite(app, backend))
    app.dependency_overrides.clear()


async def _suite(app, backend: str) -> None:
    """Весь сценарій в одному event loop.

    TestClient крутить застосунок у власному циклі, а створення замовлення
    напряму через сервіс — у поточному. Пул aiosqlite цього не пробачає:
    з'єднання лишаються прив'язаними до мертвого циклу. Тому все асинхронно.
    """
    import httpx
    from decimal import Decimal
    from shop.repo.factory import open_repo
    from shop.services import shop_service as svc

    if backend == "sql":
        from shop.db import init_db
        await init_db()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        # --- авторизація
        check("вхід з невірним паролем відхилено",
              (await client.post("/api/auth/login",
                          json={"login": "admin", "password": "wrong"})).status_code == 401)

        response = await client.post("/api/auth/login",
                               json={"login": "admin", "password": "Пароль123"})
        check("вхід з кирилицею в паролі", response.status_code == 200, response.text[:80])
        headers = {"Authorization": f"Bearer {response.json()['access_token']}"}

        check("без токена доступу немає",
              (await client.get("/api/catalog/products")).status_code == 401)

        # --- каталог
        response = await client.post("/api/catalog/categories", headers=headers,
                               json={"name": "Поди", "sort_order": 0, "is_active": True})
        check("категорія створена", response.status_code == 201, response.text[:120])
        category_id = response.json()["id"]

        response = await client.post("/api/catalog/products", headers=headers, json={
            "category_id": category_id, "name": "Elf Bar BC5000",
            "price": 400, "stock": 10, "is_active": True,
        })
        check("товар створений", response.status_code == 201, response.text[:120])
        product_id = response.json()["id"]
        check("ціна не зіпсувалась", float(response.json()["price"]) == 400.0)

        response = await client.get("/api/catalog/products", headers=headers,
                              params={"search": "elf"})
        check("пошук товару працює", len(response.json()) == 1, response.text[:120])

        response = await client.patch(f"/api/catalog/products/{product_id}/stock",
                                headers=headers, json={"stock": 7})
        check("залишок оновлено", response.json()["stock"] == 7)

        response = await client.delete(f"/api/catalog/categories/{category_id}", headers=headers)
        check("категорію з товарами не видалити", response.status_code == 409,
              f"{response.status_code}")

        # --- промокоди
        response = await client.post("/api/promos", headers=headers, json={
            "code": "TEST10", "type": "percent", "value": 10,
            "min_order": 100, "per_user_limit": 1, "is_active": True,
        })
        check("промокод створений", response.status_code == 201, response.text[:120])

        response = await client.post("/api/promos", headers=headers, json={
            "code": "test10", "type": "percent", "value": 10, "is_active": True,
        })
        check("дубль промокоду відхилено", response.status_code == 409,
              f"{response.status_code}")

        # --- замовлення через сервіс (як це робить бот), читання через API
        async with open_repo() as repo:
            user, _ = await svc.get_or_create_user(repo, 555001, "buyer", "Оля")
            await repo.confirm_age(user)
            await svc.add_to_cart(repo, user.id, product_id, 2)
            order, error = await svc.create_order(
                repo, user, contact_name="Оля К.", contact_phone="+380671112233",
                city="Київ", address="Відділення 1", payment_method="card",
                promo_code="TEST10",
            )
        check("замовлення оформлено", order is not None, str(error))
        check("знижка 10% застосована", order.discount == Decimal("80.00"), f"{order.discount}")

        response = await client.get("/api/orders", headers=headers)
        check("замовлення видно в API", len(response.json()) == 1, response.text[:120])

        response = await client.get("/api/orders", headers=headers,
                              params={"search": "0671112233"})
        check("пошук замовлення за телефоном", len(response.json()) == 1)

        response = await client.patch(f"/api/orders/{order.id}", headers=headers,
                                json={"status": "paid", "admin_note": "перевірено"})
        check("статус оновлено", response.status_code == 200, response.text[:120])
        check("нотатка збережена", response.json()["admin_note"] == "перевірено")

        # --- клієнти
        response = await client.get("/api/customers", headers=headers)
        check("клієнт у списку", len(response.json()) == 1, response.text[:120])
        customer = response.json()[0]
        check("лічильник замовлень оновився", customer["orders_count"] == 1,
              f"{customer['orders_count']}")

        response = await client.patch(f"/api/customers/{customer['id']}", headers=headers,
                                json={"bonus_delta": 100, "bonus_reason": "manual"})
        check("бонуси нараховано", float(response.json()["bonus_balance"]) == 100.0,
              response.text[:120])

        # --- статистика
        response = await client.get("/api/stats/summary", headers=headers)
        stats = response.json()
        check("виручка порахована", float(stats["revenue_total"]) == 720.0,
              f"{stats['revenue_total']}")
        check("клієнтів 1", stats["customers_total"] == 1)

        response = await client.get("/api/stats/top-products", headers=headers)
        check("топ товарів заповнений", len(response.json()) == 1, response.text[:120])

        # --- сегменти й розсилка
        response = await client.post("/api/broadcasts/preview", headers=headers,
                               json={"type": "with_orders"})
        check("сегмент 'з покупками' = 1", response.json()["count"] == 1,
              response.text[:120])

        response = await client.post("/api/broadcasts", headers=headers, json={
            "title": "Акція", "text": "Знижки!", "segment": {"type": "all"},
        })
        check("розсилка створена", response.status_code == 201, response.text[:120])
        broadcast_id = response.json()["id"]

        response = await client.get("/api/cron/broadcast-tick")
        check("cron без секрета відхилено", response.status_code == 401)

        cron_headers = {"Authorization": "Bearer cron-secret"}
        response = await client.get("/api/cron/broadcast-tick", headers=cron_headers)
        check("cron без активних розсилок", response.json()["status"] == "idle",
              response.text[:120])

        # --- вебхук
        check("вебхук з невірним секретом",
              (await client.post("/api/telegram/nope", json={})).status_code == 404)
        check("вебхук з правильним секретом",
              (await client.post("/api/telegram/hook-secret",
                                 json={"update_id": 1})).status_code == 200)

        response = await client.delete(f"/api/broadcasts/{broadcast_id}", headers=headers)
        check("розсилку видалено", response.status_code == 204)


if __name__ == "__main__":
    for backend in ("sql", "firestore"):
        run_suite(backend)
    print(f"\n{'=' * 50}\nAPI: пройдено {passed}, провалено {failed}\n{'=' * 50}")
    raise SystemExit(1 if failed else 0)
