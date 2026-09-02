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

    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:////tmp/api_test.db"
    if os.path.exists("/tmp/api_test.db"):
        os.remove("/tmp/api_test.db")

    from api.main import app

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

        # DELETE категорії — це м'яке видалення: категорія та її товари
        # зникають з бота, але лишаються в базі. Тест раніше очікував 409,
        # тобто заборону — поведінка змінилась, а перевірка ні, і сценарій
        # мовчки ховав товар, з яким далі мав збиратися кошик.
        #
        # Видаляємо окрему категорію, а не робочу: перевірка не має ламати
        # те, що йде після неї.
        response = await client.post("/api/catalog/categories", headers=headers,
                               json={"name": "Тимчасова", "sort_order": 9, "is_active": True})
        spare_id = response.json()["id"]
        response = await client.post("/api/catalog/products", headers=headers, json={
            "category_id": spare_id, "name": "Тимчасовий товар",
            "price": 100, "stock": 5, "is_active": True,
        })
        spare_product = response.json()["id"]

        response = await client.delete(f"/api/catalog/categories/{spare_id}", headers=headers)
        check("категорія прихована разом із товарами", response.status_code == 200,
              f"{response.status_code}")
        check("приховано рівно один товар", response.json()["hidden_products"] == 1,
              response.text[:120])

        response = await client.get(f"/api/catalog/products/{spare_product}", headers=headers)
        check("прихований товар лишився в базі", response.status_code == 200,
              f"{response.status_code}")
        check("але вже неактивний", response.json()["is_active"] is False,
              response.text[:120])

        response = await client.get("/api/catalog/products", headers=headers,
                              params={"search": "elf"})
        check("робочий товар не зачеплено", len(response.json()) == 1, response.text[:120])

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

        # Статуси йдуть ланцюгом, стрибки заборонені: «Нове» → «Оплачене»
        # напряму не існує. Тест раніше стрибав одразу в paid — правило
        # додали пізніше, а перевірку не оновили.
        response = await client.patch(f"/api/orders/{order.id}", headers=headers,
                                json={"status": "paid"})
        check("стрибок через статуси відхилено", response.status_code == 409,
              f"{response.status_code}")

        response = await client.patch(f"/api/orders/{order.id}", headers=headers,
                                json={"status": "accepted"})
        check("перехід у «accepted»", response.status_code == 200, response.text[:120])

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

        # Ендпоінта /api/cron більше немає: порції крутить власний
        # планувальник, а не зовнішній тікер. Замість нього перевіряємо
        # планування — те, що прийшло йому на зміну.
        from datetime import datetime, timedelta, timezone

        moment = datetime.now(timezone.utc) + timedelta(days=1)
        response = await client.post(f"/api/broadcasts/{broadcast_id}/schedule",
                               headers=headers,
                               json={"scheduled_at": moment.isoformat()})
        check("розсилку заплановано", response.status_code == 200, response.text[:120])
        check("статус став scheduled", response.json()["status"] == "scheduled",
              response.text[:120])
        check("час округлено до цілої години",
              response.json()["scheduled_at"][14:16] == "00", response.json()["scheduled_at"])

        past = datetime.now(timezone.utc) - timedelta(days=1)
        response = await client.post(f"/api/broadcasts/{broadcast_id}/schedule",
                               headers=headers, json={"scheduled_at": past.isoformat()})
        check("час у минулому відхилено", response.status_code == 422,
              f"{response.status_code}")

        response = await client.post(f"/api/broadcasts/{broadcast_id}/unschedule",
                               headers=headers)
        check("знято з черги", response.json()["status"] == "draft", response.text[:120])

        # --- вебхук
        # Адреса вебхука тепер містить ще й ідентифікатор бота. Стара адреса
        # відповідає 410, а не 404, і це не дрібниця: саме так виглядає
        # ситуація, коли в попереднього бота лишився зареєстрований вебхук
        # і він продовжує слати апдейти на ту саму адресу.
        check("стара адреса вебхука відхилена як застаріла",
              (await client.post("/api/telegram/hook-secret",
                                 json={"update_id": 1})).status_code == 410)
        check("невірний секрет не приймається",
              (await client.post("/api/telegram/nope/1", json={})).status_code == 404)
        check("вебхук з правильним секретом і ботом",
              (await client.post("/api/telegram/hook-secret/1",
                                 json={"update_id": 1})).status_code == 200)

        response = await client.delete(f"/api/broadcasts/{broadcast_id}", headers=headers)
        check("розсилку видалено", response.status_code == 204)


if __name__ == "__main__":
    run_suite("sql")
    print(f"\n{'=' * 50}\nAPI: пройдено {passed}, провалено {failed}\n{'=' * 50}")
    raise SystemExit(1 if failed else 0)
