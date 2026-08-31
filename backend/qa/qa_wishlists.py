"""СПИСКИ БАЖАНОГО: створення, вибір, додавання, показ.

Перевіряємо весь ланцюг так, як його проходить покупець: відкрив вітрину,
натиснув сердечко, створив список, поклав туди товар, перейменував,
прибрав. Кожен крок — через HTTP із справжнім initData, бо саме на стиках
(автостворення першого списку, збіг назв, чужі списки) і виникали помилки.
"""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import tempfile
import time
from decimal import Decimal
from urllib.parse import urlencode

sys.path.insert(0, "/tmp")
BOT_TOKEN = "777001:TESTTOKEN"
os.environ.update(BOT_TOKEN=BOT_TOKEN, JWT_SECRET="t" * 32,
                  ELFAR_DATA_ROOT=tempfile.mkdtemp(prefix="qa_wl_"),
                  DATABASE_URL="sqlite+aiosqlite:////tmp/qa_wishlists.db")

# Прибираємо базу від попереднього запуску. Набір, який проходить лише на
# чистій базі, гірший за відсутній: він падає через власні залишки, і час
# іде на з'ясування, що зламався тест, а не застосунок.
import pathlib  # noqa: E402

pathlib.Path("/tmp/qa_wishlists.db").unlink(missing_ok=True)

from qa_common import Report                              # noqa: E402

r = Report("СПИСКИ БАЖАНОГО")

import httpx                                              # noqa: E402
from api.main import app                                  # noqa: E402
from shop.repo.factory import open_repo                   # noqa: E402
from shop.services.wishlist import DEFAULT_WISHLIST_NAME, MAX_LISTS  # noqa: E402


def init_data(tg_id: int) -> str:
    """Підписаний initData, як його формує Telegram."""
    payload = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": tg_id, "first_name": "Тест",
                            "username": f"u{tg_id}"}, separators=(",", ":")),
    }
    check_string = "\n".join(f"{k}={payload[k]}" for k in sorted(payload))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    payload["hash"] = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(payload)


async def scenario():
    from shop.db import init_db

    await init_db()

    async with open_repo() as repo:
        category = await repo.create_category({"name": "Поди"})
        first = await repo.create_product({
            "name": "Товар А", "category_id": category.id,
            "price": Decimal(100), "stock": 5, "is_active": True})
        second = await repo.create_product({
            "name": "Товар Б", "category_id": category.id,
            "price": Decimal(200), "stock": 5, "is_active": True})

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        buyer = {"X-Telegram-Init-Data": init_data(700001)}
        stranger = {"X-Telegram-Init-Data": init_data(700002)}

        # Вік підтверджуємо: без цього всі дії зі списками відхиляються
        for headers in (buyer, stranger):
            await client.post("/api/shop/age-confirm", headers=headers)

        print("\n--- перший список створюється сам ---")
        resp = await client.get("/api/shop/wishlists", headers=buyer)
        r.check(resp.status_code == 200, "перелік віддається", resp.status_code)
        lists = resp.json()
        r.check(len(lists) == 1, "рівно один список", len(lists))
        r.check(lists[0]["name"] == DEFAULT_WISHLIST_NAME,
                f"він називається «{DEFAULT_WISHLIST_NAME}»", lists[0]["name"])
        default_id = lists[0]["id"]

        print("\n--- додавання товару ---")
        resp = await client.post(f"/api/shop/wishlists/{default_id}/items",
                                 json={"product_id": first.id}, headers=buyer)
        r.check(resp.status_code == 200, "товар додано", resp.status_code)
        r.check(len(resp.json()["product_ids"]) == 1, "у списку один товар",
                resp.json().get("product_ids"))

        # Повторне натискання сердечка має прибрати товар, а не додати вдруге
        resp = await client.post(f"/api/shop/wishlists/{default_id}/items",
                                 json={"product_id": first.id}, headers=buyer)
        r.check(len(resp.json()["product_ids"]) == 0, "повторне натискання прибирає",
                resp.json().get("product_ids"))

        await client.post(f"/api/shop/wishlists/{default_id}/items",
                          json={"product_id": first.id}, headers=buyer)
        resp = await client.post(f"/api/shop/wishlists/{default_id}/items",
                                 json={"product_id": second.id}, headers=buyer)
        r.check(len(resp.json()["product_ids"]) == 2, "два різні товари уживаються")

        print("\n--- створення власного списку ---")
        resp = await client.post("/api/shop/wishlists", json={"name": "Подарунки"},
                                 headers=buyer)
        r.check(resp.status_code == 201, "список створено", resp.status_code)
        gifts_id = resp.json()["id"]

        resp = await client.post("/api/shop/wishlists", json={"name": "Подарунки"},
                                 headers=buyer)
        r.check(resp.status_code == 409, "збіг назви — 409", resp.status_code)

        # Регістр і зайві пробіли не роблять назву іншою: інакше в переліку
        # опинилися б два однакові на вигляд списки
        for variant in ("подарунки", "  Подарунки  ", "ПОДАРУНКИ"):
            resp = await client.post("/api/shop/wishlists", json={"name": variant},
                                     headers=buyer)
            r.check(resp.status_code == 409, f"варіант написання відхилено: {variant!r}",
                    resp.status_code)

        for bad in ("", "   "):
            resp = await client.post("/api/shop/wishlists", json={"name": bad},
                                     headers=buyer)
            r.check(resp.status_code in (409, 422), f"порожня назва відхилена: {bad!r}",
                    resp.status_code)

        print("\n--- товар у кількох списках ---")
        resp = await client.post(f"/api/shop/wishlists/{gifts_id}/items",
                                 json={"product_id": first.id}, headers=buyer)
        r.check(resp.status_code == 200, "той самий товар лягає й у другий список")
        resp = await client.get("/api/shop/wishlists", headers=buyer)
        by_name = {w["name"]: w for w in resp.json()}
        r.check(len(by_name["Подарунки"]["product_ids"]) == 1, "у «Подарунках» один товар")
        r.check(len(by_name[DEFAULT_WISHLIST_NAME]["product_ids"]) == 2,
                "в «Обраному» лишились два")

        print("\n--- перейменування ---")
        resp = await client.put(f"/api/shop/wishlists/{gifts_id}",
                                json={"name": "Дні народження"}, headers=buyer)
        r.check(resp.status_code == 200, "перейменовано", resp.status_code)
        r.check(resp.json()["name"] == "Дні народження", "нова назва повернулась")
        r.check(len(resp.json()["product_ids"]) == 1, "товари не загубились",
                resp.json().get("product_ids"))

        print("\n--- чужі списки недосяжні ---")
        # Найважливіше: у списку видно, що людина збирається купити.
        for method, url, body in [
            ("post", f"/api/shop/wishlists/{gifts_id}/items", {"product_id": first.id}),
            ("put", f"/api/shop/wishlists/{gifts_id}", {"name": "Моє тепер"}),
            ("delete", f"/api/shop/wishlists/{gifts_id}", None),
        ]:
            call = getattr(client, method)
            resp = await (call(url, json=body, headers=stranger) if body
                          else call(url, headers=stranger))
            r.check(resp.status_code == 404, f"{method.upper()} чужого списку — 404",
                    resp.status_code)

        resp = await client.get("/api/shop/wishlists", headers=stranger)
        names = [w["name"] for w in resp.json()]
        r.check("Дні народження" not in names, "чужого списку не видно в переліку", names)

        print("\n--- межа кількості ---")
        created = 0
        for i in range(MAX_LISTS + 3):
            resp = await client.post("/api/shop/wishlists", json={"name": f"Список {i}"},
                                     headers=buyer)
            if resp.status_code == 201:
                created += 1
        resp = await client.get("/api/shop/wishlists", headers=buyer)
        r.check(len(resp.json()) == MAX_LISTS,
                f"більше {MAX_LISTS} не створюється", len(resp.json()))

        print("\n--- видалення ---")
        resp = await client.delete(f"/api/shop/wishlists/{gifts_id}", headers=buyer)
        r.check(resp.status_code == 204, "список видалено", resp.status_code)
        resp = await client.get("/api/shop/wishlists", headers=buyer)
        r.check(all(w["id"] != gifts_id for w in resp.json()), "його немає в переліку")

        # Після видалення назва звільняється — інакше «Список 2» назавжди
        # лишався б зайнятим, і покупець упирався б у 409 без пояснень
        resp = await client.post("/api/shop/wishlists", json={"name": "Дні народження"},
                                 headers=buyer)
        r.check(resp.status_code == 201, "звільнену назву можна взяти знову",
                resp.status_code)

        print("\n--- останній список ---")
        resp = await client.get("/api/shop/wishlists", headers=buyer)
        for item in resp.json():
            await client.delete(f"/api/shop/wishlists/{item['id']}", headers=buyer)
        resp = await client.get("/api/shop/wishlists", headers=buyer)
        r.check(len(resp.json()) == 1 and resp.json()[0]["name"] == DEFAULT_WISHLIST_NAME,
                "після видалення всіх «Обране» створюється знову",
                [w["name"] for w in resp.json()])

        print("\n--- показ у вітрині ---")
        resp = await client.get("/api/shop/bootstrap", headers=buyer)
        r.check(resp.status_code == 200, "bootstrap віддається", resp.status_code)
        r.check("wishlists" in resp.json(), "списки приходять разом із конфігурацією")


asyncio.run(scenario())
r.done()
